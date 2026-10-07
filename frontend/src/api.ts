const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Monitor {
  id: number;
  name: string;
  url: string;
  current_status: "UNKNOWN" | "UP" | "DOWN";
  last_checked_at: string | null;
  created_at: string;
}

export interface MonitorStats {
  total_checks: number;
  successful_checks: number;
  failed_checks: number;
  uptime_percentage: number | null;
  average_response_time_ms: number | null;
}

export interface Check {
  id: number;
  monitor_id: number;
  checked_at: string;
  status_code: number | null;
  response_time_ms: number | null;
  success: boolean;
  error_type: string | null;
  error_message: string | null;
}

export async function getMonitors(): Promise<Monitor[]> {
  const response = await fetch(`${API_BASE_URL}/api/monitors`);

  if (!response.ok) {
    throw new Error("Failed to load monitors");
  }

  return response.json();
}

export async function getMonitorStats(
  monitorId: number,
): Promise<MonitorStats> {
  const response = await fetch(
    `${API_BASE_URL}/api/monitors/${monitorId}/stats`,
  );

  if (!response.ok) {
    throw new Error("Failed to load monitor stats");
  }

  return response.json();
}

export async function getMonitorChecks(
  monitorId: number,
): Promise<Check[]> {
  const response = await fetch(
    `${API_BASE_URL}/api/monitors/${monitorId}/checks?limit=50`,
  );

  if (!response.ok) {
    throw new Error("Failed to load check history");
  }

  return response.json();
}


export interface CreateMonitorInput {
  name: string;
  url: string;
}

export async function createMonitor(
  input: CreateMonitorInput,
): Promise<Monitor> {
  const response = await fetch(`${API_BASE_URL}/api/monitors`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    throw new Error("Failed to create monitor");
  }

  return response.json();
}

export async function checkMonitor(
  monitorId: number,
): Promise<Check> {
  const response = await fetch(
    `${API_BASE_URL}/api/monitors/${monitorId}/check`,
    {
      method: "POST",
    },
  );

  if (!response.ok) {
    throw new Error("Failed to check monitor");
  }

  return response.json();
}

export async function deleteMonitor(
  monitorId: number,
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/monitors/${monitorId}`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw new Error("Failed to delete monitor");
  }
}