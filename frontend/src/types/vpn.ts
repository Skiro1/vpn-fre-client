export interface ProfileInfo {
  name: string;
  address: string;
  endpoint: string;
  account_id: string;
  warp_plus: boolean;
}

export interface VpnStatus {
  connected: boolean;
  profile: string;
  address: string;
  endpoint: string;
  tx_bytes: number;
  rx_bytes: number;
  uptime: string;
}
