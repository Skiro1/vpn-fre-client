package vpn

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"net"
	"os/exec"
	"strings"
	"sync"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/conn"
	"github.com/amnezia-vpn/amneziawg-go/device"
	"github.com/amnezia-vpn/amneziawg-go/ipc"
	"github.com/amnezia-vpn/amneziawg-go/ipc/namedpipe"
	"github.com/amnezia-vpn/amneziawg-go/tun"
	"github.com/amnezia-vpn/amneziawg-windows/tunnel/winipcfg"
	"golang.org/x/sys/windows"
)

type TunnelManager struct {
	mu         sync.Mutex
	activeTun  *activeTunnel
}

type activeTunnel struct {
	dev       *device.Device
	tun       tun.Device
	uapi      net.Listener
	intf      string
	profile   *Profile
	settings  *Settings
	stopCh    chan struct{}
	startedAt time.Time
	closeOnce sync.Once
}

func NewTunnelManager() *TunnelManager {
	return &TunnelManager{}
}

func (tm *TunnelManager) Up(profile *Profile, settings *Settings) error {
	tm.mu.Lock()
	defer tm.mu.Unlock()

	if tm.activeTun != nil {
		return fmt.Errorf("tunnel already active")
	}

	logger := device.NewLogger(device.LogLevelVerbose, "(vpn) ")

	tundev, err := tun.CreateTUN("warp0", 1280)
	if err != nil {
		return fmt.Errorf("create TUN: %w", err)
	}

	intfName := "warp0"
	if name, err := tundev.Name(); err == nil {
		intfName = name
	}

	at := &activeTunnel{
		tun:       tundev,
		intf:      intfName,
		profile:   profile,
		settings:  settings,
		stopCh:    make(chan struct{}),
		startedAt: time.Now(),
	}

	bind := conn.NewDefaultBind()
	at.dev = device.NewDevice(tundev, bind, logger)

	sd, err := windows.SecurityDescriptorFromString("D:(A;;GA;;;WD)")
	if err != nil {
		at.dev.Close()
		tundev.Close()
		return fmt.Errorf("create security descriptor: %w", err)
	}
	ipc.UAPISecurityDescriptor = sd

	uapi, err := ipc.UAPIListen(intfName)
	if err != nil {
		at.dev.Close()
		tundev.Close()
		return fmt.Errorf("uapi listen: %w", err)
	}
	at.uapi = uapi

	go func() {
		for {
			conn, err := uapi.Accept()
			if err != nil {
				return
			}
			go at.dev.IpcHandle(conn)
		}
	}()

	if err := configureDevice(at.dev, profile); err != nil {
		at.close()
		return fmt.Errorf("configure device: %w", err)
	}

	if err := at.dev.Up(); err != nil {
		at.close()
		return fmt.Errorf("device up: %w", err)
	}

	if err := configureNetwork(intfName, profile, settings); err != nil {
		at.close()
		return fmt.Errorf("configure network: %w", err)
	}

	if settings.KillSwitch {
		if err := enableKillSwitch(profile.Endpoint); err != nil {
			at.close()
			return fmt.Errorf("kill switch: %w", err)
		}
	}

	tm.activeTun = at
	return nil
}

func (tm *TunnelManager) Down() error {
	tm.mu.Lock()
	defer tm.mu.Unlock()

	if tm.activeTun == nil {
		return fmt.Errorf("no active tunnel")
	}

	tm.activeTun.close()
	tm.activeTun = nil
	return nil
}

func (tm *TunnelManager) Status() *VpnStatus {
	tm.mu.Lock()
	defer tm.mu.Unlock()

	status := &VpnStatus{
		Connected: false,
	}

	if tm.activeTun == nil {
		return status
	}

	at := tm.activeTun
	status.Connected = true
	status.Profile = at.profile.Name
	status.Address = at.profile.Address
	status.Endpoint = at.profile.Endpoint
	status.Uptime = time.Since(at.startedAt).Round(time.Second).String()

	if out, err := at.dev.IpcGet(); err == nil {
		for _, line := range strings.Split(out, "\n") {
			if strings.HasPrefix(line, "tx_bytes=") {
				fmt.Sscanf(line, "tx_bytes=%d", &status.TXBytes)
			} else if strings.HasPrefix(line, "rx_bytes=") {
				fmt.Sscanf(line, "rx_bytes=%d", &status.RXBytes)
			}
		}
	}

	return status
}

func (tm *TunnelManager) IsActive() bool {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	return tm.activeTun != nil
}

func (at *activeTunnel) close() {
	at.closeOnce.Do(func() {
		if at.settings != nil && at.settings.KillSwitch {
			disableKillSwitch()
		}

		if at.tun != nil {
			if nativeTun, ok := at.tun.(*tun.NativeTun); ok {
				luid := winipcfg.LUID(nativeTun.LUID())
				luid.FlushRoutes(windows.AF_INET)
				luid.FlushIPAddresses(windows.AF_INET)
				luid.FlushDNS(windows.AF_INET)
			}
		}

		if at.uapi != nil {
			at.uapi.Close()
		}

		if at.dev != nil {
			done := make(chan struct{})
			go func() {
				at.dev.Close()
				close(done)
			}()
			select {
			case <-done:
			case <-time.After(3 * time.Second):
			}
		}

		close(at.stopCh)
	})
}

func b64toHex(b64 string) (string, error) {
	raw, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		return "", err
	}
	return hex.EncodeToString(raw), nil
}

func configureDevice(dev *device.Device, profile *Profile) error {
	pipeName := fmt.Sprintf(`\\.\pipe\ProtectedPrefix\Administrators\AmneziaWG\%s`, "warp0")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	conn, err := namedpipe.DialContext(ctx, pipeName)
	if err != nil {
		return fmt.Errorf("dial uapi pipe: %w", err)
	}
	defer conn.Close()

	var cmd strings.Builder
	cmd.WriteString("set=1\n")

	privHex, err := b64toHex(profile.PrivateKey)
	if err != nil {
		return fmt.Errorf("convert private key: %w", err)
	}
	fmt.Fprintf(&cmd, "private_key=%s\n", privHex)

	awg := profile.AWG
	fmt.Fprintf(&cmd, "jc=%d\n", awg.Jc)
	fmt.Fprintf(&cmd, "jmin=%d\n", awg.Jmin)
	fmt.Fprintf(&cmd, "jmax=%d\n", awg.Jmax)
	fmt.Fprintf(&cmd, "s1=%d\n", awg.S1)
	fmt.Fprintf(&cmd, "s2=%d\n", awg.S2)
	if awg.H1 != "" && awg.H1 != "0" {
		fmt.Fprintf(&cmd, "h1=%s\n", awg.H1)
	}
	if awg.H2 != "" && awg.H2 != "0" {
		fmt.Fprintf(&cmd, "h2=%s\n", awg.H2)
	}
	if awg.H3 != "" && awg.H3 != "0" {
		fmt.Fprintf(&cmd, "h3=%s\n", awg.H3)
	}
	if awg.H4 != "" && awg.H4 != "0" {
		fmt.Fprintf(&cmd, "h4=%s\n", awg.H4)
	}
	for i, v := range []string{awg.I1, awg.I2, awg.I3, awg.I4, awg.I5} {
		if v != "" {
			fmt.Fprintf(&cmd, "i%d=%s\n", i+1, v)
		}
	}

	pubHex, err := b64toHex(profile.PublicKey)
	if err != nil {
		return fmt.Errorf("convert public key: %w", err)
	}
	fmt.Fprintf(&cmd, "public_key=%s\n", pubHex)

	host := profile.Endpoint
	if !strings.Contains(host, ":") {
		host = host + ":2408"
	}
	hostIP, port, err := net.SplitHostPort(host)
	if err != nil {
		return fmt.Errorf("parse endpoint: %w", err)
	}
	if net.ParseIP(hostIP) == nil {
		ips, err := net.LookupHost(hostIP)
		if err == nil && len(ips) > 0 {
			hostIP = ips[0]
		}
	}
	fmt.Fprintf(&cmd, "endpoint=%s:%s\n", hostIP, port)

	cmd.WriteString("allowed_ip=0.0.0.0/0\n")
	cmd.WriteString("allowed_ip=::/0\n")
	cmd.WriteString("persistent_keepalive_interval=25\n")
	cmd.WriteString("\n")

	if _, err := conn.Write([]byte(cmd.String())); err != nil {
		return fmt.Errorf("write uapi config: %w", err)
	}

	buf := make([]byte, 4096)
	n, err := conn.Read(buf)
	if err != nil {
		return fmt.Errorf("read uapi response: %w", err)
	}

	resp := strings.TrimSpace(string(buf[:n]))
	if resp != "OK" && !strings.HasPrefix(resp, "errno=0") {
		return fmt.Errorf("uapi config failed: %s", resp)
	}

	return nil
}

func configureNetwork(intfName string, profile *Profile, settings *Settings) error {
	addr := strings.Split(profile.Address, "/")[0]

	runCmd(fmt.Sprintf(`netsh interface ip set address "%s" static %s 255.255.255.255`, intfName, addr))
	runCmd(fmt.Sprintf(`netsh interface ip set dns "%s" static %s register=primary`, intfName, settings.Dns))

	host := profile.Endpoint
	if !strings.Contains(host, ":") {
		host = host + ":2408"
	}
	hostIP, _, _ := net.SplitHostPort(host)
	if net.ParseIP(hostIP) == nil {
		ips, err := net.LookupHost(hostIP)
		if err == nil {
			for _, ip := range ips {
				if p := net.ParseIP(ip); p != nil && p.To4() != nil {
					hostIP = ip
					break
				}
			}
		}
	}

	gw := getDefaultGateway()
	if hostIP != "" && gw != "" {
		runCmd(fmt.Sprintf(`route add %s mask 255.255.255.255 %s`, hostIP, gw))
	}

	runCmd(fmt.Sprintf(`netsh interface ip add route 0.0.0.0/0 "%s" %s metric=0 store=active`, intfName, addr))

	if profile.Address6 != "" {
		addr6 := strings.Split(profile.Address6, "/")[0]
		runCmd(fmt.Sprintf(`netsh interface ipv6 set address "%s" %s`, intfName, addr6))
		runCmd(fmt.Sprintf(`netsh interface ipv6 add route ::/0 "%s" %s metric=0 store=active`, intfName, addr6))
	}

	return nil
}

func getDefaultGateway() string {
	out, err := runCmdOutput(`route print 0.0.0.0`)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "0.0.0.0") {
			fields := strings.Fields(line)
			if len(fields) >= 3 {
				gw := fields[2]
				if ip := net.ParseIP(gw); ip != nil && !ip.Equal(net.IPv4zero) {
					return gw
				}
			}
		}
	}
	return ""
}

func runCmd(cmd string) error {
	c := exec.Command("cmd", "/c", cmd)
	return c.Run()
}

func runCmdOutput(cmd string) (string, error) {
	c := exec.Command("cmd", "/c", cmd)
	out, err := c.CombinedOutput()
	return strings.TrimSpace(string(out)), err
}

func enableKillSwitch(endpoint string) error {
	if ep := extractIP(endpoint); ep != "" {
		runCmd(fmt.Sprintf(`netsh advfirewall firewall add rule name="SKKVPN Allow EP" dir=out action=allow remoteip=%s`, ep))
	}
	return runCmd(`netsh advfirewall firewall add rule name="SKKVPN Block" dir=out action=block`)
}

func disableKillSwitch() {
	runCmd(`netsh advfirewall firewall delete rule name="SKKVPN Allow EP"`)
	runCmd(`netsh advfirewall firewall delete rule name="SKKVPN Block"`)
}

func extractIP(endpoint string) string {
	if !strings.Contains(endpoint, ":") {
		endpoint = endpoint + ":2408"
	}
	host, _, err := net.SplitHostPort(endpoint)
	if err != nil {
		return ""
	}
	if ip := net.ParseIP(host); ip != nil {
		return host
	}
	ips, err := net.LookupHost(host)
	if err != nil || len(ips) == 0 {
		return ""
	}
	return ips[0]
}
