import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

export async function getServerStatus() {
  return invoke('get_server_status');
}

export async function startServer() {
  return invoke('start_server');
}

export async function stopServer() {
  return invoke('stop_server');
}

export async function openDashboard(port) {
  return invoke('open_dashboard', { port });
}

export async function getSettings() {
  return invoke('get_settings');
}

export async function updateSettings(settings) {
  return invoke('update_settings', { settings });
}

export async function checkUpdate() {
  return invoke('check_update');
}

export async function installUpdate() {
  return invoke('install_update');
}

const API_BASE = 'http://localhost:8080';

export async function fetchTrades() {
  const res = await fetch(`${API_BASE}/api/trades`);
  return res.json();
}

export async function discoverLeads(trade, location) {
  const res = await fetch(`${API_BASE}/api/trades/discover`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ trade, location })
  });
  return res.json();
}

export async function convertLead(data) {
  const res = await fetch(`${API_BASE}/api/trades/convert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

export async function fetchRevenue() {
  const res = await fetch(`${API_BASE}/api/trades/revenue`);
  return res.json();
}

export async function getVaultKeys() {
  return invoke('get_vault_keys');
}

export async function setVaultKey(service, key) {
  return invoke('set_vault_key', { service, key });
}

export async function deleteVaultKey(service) {
  return invoke('delete_vault_key', { service });
}

export async function getEnrichProviders() {
  return invoke('get_enrich_providers');
}

export async function enrichLead(businessName, trade, location) {
  return invoke('enrich_lead', { businessName, trade, location });
}

export async function fetchVaultKeys() {
  const res = await fetch(`${API_BASE}/api/vault/keys`);
  return res.json();
}

export async function fetchEnrichProviders() {
  const res = await fetch(`${API_BASE}/api/enrich/providers`);
  return res.json();
}

export async function postEnrichLead(businessName, trade, location) {
  const res = await fetch(`${API_BASE}/api/enrich/lead`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ business_name: businessName, trade, location })
  });
  return res.json();
}

listen('server-status', (event) => {
  window.dispatchEvent(new CustomEvent('server-status', { detail: event.payload }));
});
