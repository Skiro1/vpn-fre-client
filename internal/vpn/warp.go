package vpn

import (
	"bytes"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"golang.org/x/crypto/curve25519"
)

const (
	apiBaseURL = "https://api.cloudflareclient.com"
	apiVersion = "v0a2158"
	userAgent  = "okhttp/3.12.1"
	apiTimeout = 15 * time.Second
)

type RegisterRequest struct {
	Key         string `json:"key"`
	InstallID   string `json:"install_id"`
	FCMToken    string `json:"fcm_token"`
	Referer     string `json:"referer"`
	WarpEnabled bool   `json:"warp_enabled"`
	Locale      string `json:"locale"`
	License     string `json:"license,omitempty"`
}

type RegisterResponse struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Token    string `json:"token"`
	ClientID string `json:"client_id"`
	Config   struct {
		ClientID  string `json:"client_id"`
		Peers     []struct {
			PublicKey string `json:"public_key"`
			Endpoint struct {
				Host  string `json:"host"`
				V4    string `json:"v4"`
				V6    string `json:"v6"`
				Ports []int  `json:"ports"`
			} `json:"endpoint"`
		} `json:"peers"`
		Interface struct {
			Addresses struct {
				V4 string `json:"v4"`
				V6 string `json:"v6"`
			} `json:"addresses"`
		} `json:"interface"`
	} `json:"config"`
	WarpPlus bool `json:"warp_plus"`
	Account  struct {
		ID string `json:"id"`
	} `json:"account"`
}

type WarpClient struct {
	httpClient *http.Client
}

func NewWarpClient() *WarpClient {
	return &WarpClient{
		httpClient: &http.Client{Timeout: apiTimeout},
	}
}

func GenerateKeyPair() (privateKey, publicKey string, err error) {
	var sk [32]byte
	if _, err := rand.Read(sk[:]); err != nil {
		return "", "", fmt.Errorf("generate private key: %w", err)
	}
	sk[0] &= 248
	sk[31] &= 127
	sk[31] |= 64

	var pk [32]byte
	curve25519.ScalarBaseMult(&pk, &sk)

	privateKey = base64.StdEncoding.EncodeToString(sk[:])
	publicKey = base64.StdEncoding.EncodeToString(pk[:])
	return privateKey, publicKey, nil
}

func (c *WarpClient) Register(req *RegisterRequest) (*RegisterResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequest("POST", apiBaseURL+"/"+apiVersion+"/reg", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("User-Agent", userAgent)

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error (status %d): %s", resp.StatusCode, string(respBody))
	}

	var result RegisterResponse
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("unmarshal response: %w, body: %s", err, string(respBody))
	}

	return &result, nil
}

func (c *WarpClient) KeepAlive(token, accountID string) error {
	path := "/" + apiVersion + "/reg/" + accountID
	body := `{"warp_enabled":true}`

	req, err := http.NewRequest("PATCH", apiBaseURL+path, strings.NewReader(body))
	if err != nil {
		return fmt.Errorf("create keepalive request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("keepalive request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusNoContent {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("keepalive API error (status %d): %s", resp.StatusCode, string(respBody))
	}

	return nil
}
