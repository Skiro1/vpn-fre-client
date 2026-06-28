package vpn

import "time"

type AWGConfig struct {
	Jc   int    `json:"jc"`
	Jmin int    `json:"jmin"`
	Jmax int    `json:"jmax"`
	S1   int    `json:"s1"`
	S2   int    `json:"s2"`
	S3   int    `json:"s3"`
	S4   int    `json:"s4"`
	H1   string `json:"h1"`
	H2   string `json:"h2"`
	H3   string `json:"h3"`
	H4   string `json:"h4"`
	I1   string `json:"i1"`
	I2   string `json:"i2"`
	I3   string `json:"i3"`
	I4   string `json:"i4"`
	I5   string `json:"i5"`
}

type Profile struct {
	Name       string    `json:"name"`
	PrivateKey string    `json:"private_key"`
	Address    string    `json:"address"`
	Address6   string    `json:"address6"`
	DNS        string    `json:"dns"`
	PublicKey  string    `json:"public_key"`
	Endpoint   string    `json:"endpoint"`
	AccountID  string    `json:"account_id"`
	ClientID   string    `json:"client_id"`
	Token      string    `json:"token"`
	License    string    `json:"license,omitempty"`
	AWG        AWGConfig `json:"awg"`
}

type VpnStatus struct {
	Connected bool   `json:"connected"`
	Profile   string `json:"profile"`
	Address   string `json:"address"`
	Endpoint  string `json:"endpoint"`
	TXBytes   int64  `json:"tx_bytes"`
	RXBytes   int64  `json:"rx_bytes"`
	Uptime    string `json:"uptime"`
}

type Settings struct {
	Dns        string `json:"dns"`
	KillSwitch bool   `json:"kill_switch"`
}

var DefaultSettings = Settings{
	Dns:        "1.1.1.1",
	KillSwitch: true,
}

type EndpointInfo struct {
	Address string `json:"address"`
	RTT     string `json:"rtt"`
}

type TunnelState struct {
	InterfaceName string
	Profile       *Profile
	StopCh        chan struct{}
	StartedAt     time.Time
}
