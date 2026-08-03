# Thermal Orchestrator

[Tiếng Việt](README.md) | English

Thermal Orchestrator is a Windows proof of concept for distributing AI work
based on the real temperature and power draw of several machines. The Host
stores telemetry, forecasts thermal risk, selects a suitable node for each job,
and streams chat tokens to the browser through WebSocket. Each worker only
opens outbound connections to the Host; workers never listen on a port.

## What runs for real

- `ThermalOrchestrator.exe`: a self-contained Host containing the Python
  runtime, server, and NodeAgent.
- `NodeAgent.exe`: reads CPU/GPU/power sensors, receives jobs, and runs
  llama.cpp.
- SQLite: stores telemetry, operational audit records, and ESG data separated
  by source.
- LLM chat: dispatches only to nodes reporting `READY` with the selected
  model, hash, generation, and runtime identity.
- Cloudflare Tunnel: Quick Tunnel for trials or Named Tunnel with a stable
  hostname. An invite link is displayed only after a public HTTPS probe passes.

## Quick start with one EXE

1. Download [ThermalOrchestrator.exe](publish/ThermalOrchestrator/ThermalOrchestrator.exe).
2. Double-click the EXE and accept the UAC prompt. On first run it extracts
   the payload to `%ProgramData%\ThermalOrchestrator\versions` and starts the
   Host at `http://127.0.0.1:8000`.
3. On the landing page, choose **Create a room on this computer**. Set separate
   worker and admin passwords of at least 12 Unicode characters.
4. The Host starts its local NodeAgent automatically. Wait for the Host state
   to become `READY`; the first model download/start may take several minutes.
5. Sign in as an admin, select a model, and send a chat request. The send button
   is enabled only when a matching node is `READY`.

To update, run the new EXE with:

```powershell
.\ThermalOrchestrator.exe --update
```

The updater requests UAC, stops only Python/NodeAgent processes located below
Thermal Orchestrator's version directory, installs the new payload, and starts
the Host again. Do not use Task Manager to launch an additional NodeAgent when
the Host already has one: a Host should have one local NodeAgent and one
`llama-server` owned by that agent.

## Add a worker machine

From the admin dashboard, copy the **worker setup link** (not the admin sign-in
link) and give it together with `NodeAgent.exe` to the worker machine.

On the Windows worker:

```powershell
.\NodeAgent.exe --setup "https://host.example/worker-setup?code=THERMAL-XXXX"
```

The wizard asks for a unique node name, Host LAN/tunnel URL, and worker password
in a masked field. It rejects `localhost` on a different computer, writes a
machine-scoped DPAPI-encrypted configuration, and starts the agent. Accept UAC
so hardware sensors are available. A worker needs no inbound firewall rule or
port forwarding.

For a LAN deployment, use a URL such as `http://192.168.x.x:8000`. Open TCP
port 8000 in Windows Firewall on the Host if it blocks LAN connections.

## Tunnel and Internet invite link

Sign in as an admin and choose one of these tunnel modes:

- **Quick**: random `trycloudflare.com` URL for trials.
- **Named**: requires a hostname and Cloudflare token; intended for stable
  acceptance testing.

Tunnel activation requires both room passwords to be at least 12 characters.
Once the state is `READY`, the dashboard shows a worker link to copy. The link
does not include a password; the worker enters it in the setup wizard.

## Check sensors and processes

Open an Administrator PowerShell prompt:

```powershell
.\NodeAgent.exe --test-sensors
```

A valid result includes CPU/GPU temperature, CPU utilization, and power. If a
value is `n/a`, check UAC, the LibreHardwareMonitor driver, and the hardware;
do not treat stale values as live telemetry.

A healthy Host has exactly:

1. One payload-owned `python.exe` Host process.
2. One NodeAgent from the same payload version.
3. At most one `llama-server.exe`, whose parent is NodeAgent.

Two `llama-server` processes on one Host are not a load-balancing feature. They
compete for CPU and RAM and should be resolved through a Host update/restart,
not by launching another agent.

## Run from source

Requirements: Windows 10/11, Python 3.11+, and the .NET 8 SDK. From the
repository root:

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
python server.py
```

Open `http://127.0.0.1:8000`. To publish the agent and Host EXE:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\publish_agent.ps1
powershell -ExecutionPolicy Bypass -File scripts\publish_orchestrator.ps1 `
  -PythonRuntimeDir artifacts\python-runtime -Version dev
```

## Tests

```powershell
server\.venv\Scripts\python.exe -m pytest server\tests\ -q
dotnet test agent\NodeAgent.Tests\NodeAgent.Tests.csproj -c Release
```

Verified result: Python `351/351`, .NET `55/55`.

See [HOW_IT_WORKS.en.md](HOW_IT_WORKS.en.md) for architecture and operations,
or [PROJECT_OVERVIEW.en.md](PROJECT_OVERVIEW.en.md) for product scope, results,
and PoC limitations.
