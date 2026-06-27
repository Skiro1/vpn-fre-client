package main

import (
	"fmt"
	"strings"

	"github.com/skkvpn/free-vpn-new/internal/vpn"
)

type VpnService struct {
	client  *vpn.WarpClient
	tunnel  *vpn.TunnelManager
}

func NewVpnService() *VpnService {
	return &VpnService{
		client: vpn.NewWarpClient(),
		tunnel: vpn.NewTunnelManager(),
	}
}

func (s *VpnService) Register(profileName string, license string) (*ProfileInfo, error) {
	existing, _ := vpn.LoadProfile(profileName)
	if existing != nil && existing.PrivateKey != "" {
		return nil, fmt.Errorf("profile %q already exists", profileName)
	}

	privKey, pubKey, err := vpn.GenerateKeyPair()
	if err != nil {
		return nil, fmt.Errorf("generate keys: %w", err)
	}

	req := &vpn.RegisterRequest{
		Key:         pubKey,
		WarpEnabled: true,
		Locale:      "en-US",
	}
	if license != "" {
		req.License = license
	}

	resp, err := s.client.Register(req)
	if err != nil {
		return nil, fmt.Errorf("register with WARP: %w", err)
	}

	endpoint := vpn.DefaultEndpoint
	if len(resp.Config.Peers) > 0 {
		peer := resp.Config.Peers[0]
		if peer.Endpoint.Host != "" {
			endpoint = peer.Endpoint.Host
			if !strings.Contains(endpoint, ":") {
				endpoint = fmt.Sprintf("%s:%d", endpoint, 2408)
			}
		} else if peer.Endpoint.V4 != "" {
			endpoint = fmt.Sprintf("%s:%d", peer.Endpoint.V4, 2408)
		}
	}

	profile := &vpn.Profile{
		Name:       profileName,
		PrivateKey: privKey,
		Address:    resp.Config.Interface.Addresses.V4,
		Address6:   resp.Config.Interface.Addresses.V6,
		DNS:        vpn.DefaultDNS,
		PublicKey:  resp.Config.Peers[0].PublicKey,
		Endpoint:   endpoint,
		AccountID:  resp.ID,
		ClientID:   resp.Config.ClientID,
		Token:      resp.Token,
		License:    license,
		AWG:        vpn.DefaultAWG,
	}

	if err := profile.Save(); err != nil {
		return nil, fmt.Errorf("save profile: %w", err)
	}

	return toProfileInfo(profile), nil
}

func (s *VpnService) Connect(profileName string) error {
	profile, err := vpn.LoadProfile(profileName)
	if err != nil {
		return fmt.Errorf("load profile: %w", err)
	}

	if profile.Token != "" {
		if err := s.client.KeepAlive(profile.Token, profile.AccountID); err != nil {
			fmt.Printf("keepalive warning: %v\n", err)
		}
	}

	return s.tunnel.Up(profile)
}

func (s *VpnService) Disconnect() error {
	return s.tunnel.Down()
}

func (s *VpnService) GetStatus() *vpn.VpnStatus {
	return s.tunnel.Status()
}

func (s *VpnService) ListProfiles() ([]*ProfileInfo, error) {
	names, err := vpn.ListProfiles()
	if err != nil {
		return nil, err
	}
	var result []*ProfileInfo
	for _, name := range names {
		p, err := vpn.LoadProfile(name)
		if err != nil {
			continue
		}
		result = append(result, toProfileInfo(p))
	}
	return result, nil
}

func (s *VpnService) GetProfile(name string) (*ProfileInfo, error) {
	p, err := vpn.LoadProfile(name)
	if err != nil {
		return nil, err
	}
	return toProfileInfo(p), nil
}

func (s *VpnService) DeleteProfile(name string) error {
	if s.tunnel.IsActive() {
		return fmt.Errorf("disconnect before deleting profile")
	}
	return vpn.DeleteProfile(name)
}

type ProfileInfo struct {
	Name     string `json:"name"`
	Address  string `json:"address"`
	Endpoint string `json:"endpoint"`
	AccountID string `json:"account_id"`
	WarpPlus bool   `json:"warp_plus"`
}

func toProfileInfo(p *vpn.Profile) *ProfileInfo {
	return &ProfileInfo{
		Name:      p.Name,
		Address:   p.Address,
		Endpoint:  p.Endpoint,
		AccountID: p.AccountID,
		WarpPlus:  p.License != "",
	}
}
