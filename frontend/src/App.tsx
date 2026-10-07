import { useEffect, useState } from "react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  checkMonitor,
  createMonitor,
  deleteMonitor,
  getMonitorChecks,
  getMonitors,
  getMonitorStats,
  type Check,
  type Monitor,
  type MonitorStats,
} from "./api";
import "./App.css";

interface MonitorWithStats extends Monitor {
  stats: MonitorStats | null;
  checks: Check[];
}

function App() {
  const [monitors, setMonitors] = useState<MonitorWithStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  async function loadDashboard() {
    try {
      setError(null);

      const monitorList = await getMonitors();

      const monitorsWithStats = await Promise.all(
        monitorList.map(async (monitor) => {
          try {
            const [stats, checks] = await Promise.all([
              getMonitorStats(monitor.id),
              getMonitorChecks(monitor.id),
            ]);

            return {
              ...monitor,
              stats,
              checks: [...checks].reverse(),
            };
          } catch {
            return {
              ...monitor,
              stats: null,
              checks: [],
            };
          }
        }),
      );

      setMonitors(monitorsWithStats);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to load dashboard",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    Promise.resolve().then(() => loadDashboard());
  }, []);

  async function handleCreateMonitor(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    setCreating(true);
    setFormError(null);

    try {
      const monitor = await createMonitor({
        name: newName.trim(),
        url: newUrl.trim(),
      });

      await checkMonitor(monitor.id);

      setNewName("");
      setNewUrl("");
      setShowAddForm(false);

      await loadDashboard();
    } catch (err) {
      setFormError(
        err instanceof Error
          ? err.message
          : "Failed to create monitor",
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleDeleteMonitor(monitor: Monitor) {
  const confirmed = window.confirm(
    `Delete "${monitor.name}"?\n\nIts check and incident history will also be deleted.`,
  );

  if (!confirmed) {
    return;
  }

  setDeletingId(monitor.id);

  try {
    await deleteMonitor(monitor.id);

    setMonitors((current) =>
      current.filter((item) => item.id !== monitor.id),
    );
  } catch (err) {
    setError(
      err instanceof Error
        ? err.message
        : "Failed to delete monitor",
    );
  } finally {
    setDeletingId(null);
  }
}

  if (loading) {
    return <main className="page">Loading monitors...</main>;
  }

  if (error) {
    return <main className="page error">Error: {error}</main>;
  }

  return (
    <main className="page">
      <header className="header">
        <div>
          <h1>API Health Monitor</h1>
          <p>Monitor uptime and response times from one place.</p>
        </div>

        <button
          className="primary-button"
          onClick={() => setShowAddForm(true)}
        >
          + Add Monitor
        </button>
      </header>

      {showAddForm && (
        <form className="add-form" onSubmit={handleCreateMonitor}>
          <div className="form-heading">
            <div>
              <h2>Add monitor</h2>
              <p>Enter an HTTP or HTTPS endpoint to monitor.</p>
            </div>

            <button
              type="button"
              className="close-button"
              onClick={() => setShowAddForm(false)}
            >
              ×
            </button>
          </div>

          <div className="form-fields">
            <label>
              Name
              <input
                type="text"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                placeholder="Payments API"
                required
              />
            </label>

            <label>
              URL
              <input
                type="url"
                value={newUrl}
                onChange={(event) => setNewUrl(event.target.value)}
                placeholder="https://api.example.com/health"
                required
              />
            </label>
          </div>

          {formError && <p className="form-error">{formError}</p>}

          <div className="form-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => setShowAddForm(false)}
            >
              Cancel
            </button>

            <button
              type="submit"
              className="primary-button"
              disabled={creating}
            >
              {creating ? "Adding..." : "Add Monitor"}
            </button>
          </div>
        </form>
      )}

      <section className="summary">
        <div>
          <span>Total</span>
          <strong>{monitors.length}</strong>
        </div>

        <div>
          <span>Up</span>
          <strong>
            {
              monitors.filter(
                (monitor) => monitor.current_status === "UP",
              ).length
            }
          </strong>
        </div>

        <div>
          <span>Down</span>
          <strong>
            {
              monitors.filter(
                (monitor) => monitor.current_status === "DOWN",
              ).length
            }
          </strong>
        </div>
      </section>

      <section className="monitor-grid">
        {monitors.map((monitor) => (
          <article className="monitor-card" key={monitor.id}>
            <div className="monitor-heading">
              <div>
                <h2>{monitor.name}</h2>

                <a
                  href={monitor.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {monitor.url}
                </a>
              </div>

              <span
                className={`status status-${monitor.current_status.toLowerCase()}`}
              >
                <span className="status-dot" />
                {monitor.current_status}
              </span>
            </div>

            <div className="metrics">
              <div>
                <span>Uptime</span>
                <strong>
                  {monitor.stats?.uptime_percentage != null
                    ? `${monitor.stats.uptime_percentage}%`
                    : "—"}
                </strong>
              </div>

              <div>
                <span>Avg response</span>
                <strong>
                  {monitor.stats?.average_response_time_ms != null
                    ? `${Math.round(
                        monitor.stats.average_response_time_ms,
                      )} ms`
                    : "—"}
                </strong>
              </div>

              <div>
                <span>Checks</span>
                <strong>{monitor.stats?.total_checks ?? "—"}</strong>
              </div>
            </div>

            <div className="chart">
              <div className="chart-header">
                <span>Response time</span>
                <span>Last {monitor.checks.length} checks</span>
              </div>

              {monitor.checks.length > 1 ? (
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={monitor.checks}>
                    <XAxis
                      dataKey="checked_at"
                      tickFormatter={(value: string) =>
                        new Date(value).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      }
                      tick={{ fontSize: 11 }}
                      minTickGap={30}
                    />

                    <YAxis
                      width={55}
                      tick={{ fontSize: 11 }}
                      tickFormatter={(value: number) => `${value}ms`}
                    />

                    <Tooltip
                      labelFormatter={(value) =>
                        new Date(String(value)).toLocaleString()
                      }
                      formatter={(value) => [
                        `${value ?? "—"} ms`,
                        "Response",
                      ]}
                    />

                    <Line
                      type="monotone"
                      dataKey="response_time_ms"
                      stroke="currentColor"
                      strokeWidth={2}
                      dot={false}
                      connectNulls={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="chart-empty">
                  Not enough check history yet.
                </div>
              )}
            </div>

            <footer className="monitor-footer">
              <span>
                Last checked:{" "}
                {monitor.last_checked_at
                  ? new Date(monitor.last_checked_at).toLocaleString()
                  : "Never"}
              </span>

              <button
                className="delete-button"
                type="button"
                disabled={deletingId === monitor.id}
                onClick={() => void handleDeleteMonitor(monitor)}
              >
                {deletingId === monitor.id ? "Deleting..." : "Delete"}
              </button>
            </footer>
          </article>
        ))}
      </section>
    </main>
  );
}

export default App;