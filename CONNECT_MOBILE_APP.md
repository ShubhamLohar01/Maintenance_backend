# Connecting the FactoryOps mobile app to this backend

The FactoryOps Android app (Kotlin, Jetpack Compose, MVVM + Hilt + Room +
Retrofit) lives at `d:\Maintenance module\FactoryOps`. It ships with an
in-app mock layer behind a `BuildConfig.USE_MOCK_API` flag. This guide
explains how to flip that flag and point Retrofit at the Python backend
in this folder.

---

## 0. Prerequisites

1. **Backend is running** on this machine. From `d:\Maintenance module\backend`:
   ```powershell
   python -m scripts.seed                                          # one-time
   python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   With the dev tunnel forwarding the port (next step), you do **not** need
   `--host 0.0.0.0` — the tunnel reads from `127.0.0.1:8000` on this machine.

2. **Dev tunnel (recommended)** — you have forwarded port 8000 to:

   ```
   https://8vp3hks5-8000.inc1.devtunnels.ms/
   ```

   This is what every phone / emulator / external tester should hit. It's
   **HTTPS**, publicly reachable, and survives the laptop being on any
   network — so the LAN-IP / Wi-Fi / Windows-Firewall steps below are *not
   needed when the tunnel is up*.

   Confirm it works from any browser:
   `https://8vp3hks5-8000.inc1.devtunnels.ms/health` → `{"status":"ok"}`.

   > **Heads-up:** VS Code dev tunnels show an HTML interstitial ("Continue
   > to the tunnel") on the **first** request from a new browser if the
   > tunnel's access is set to *Private* or *Org*. Set the port visibility
   > to **Public** in VS Code's **Ports** panel (right-click the port →
   > *Port Visibility → Public*) so the Kotlin Retrofit client doesn't get
   > served HTML it can't parse.
   >
   > Dev-tunnel URLs are stable as long as the tunnel session is up. If you
   > stop the tunnel and restart it, you may get a new subdomain — update
   > `BASE_URL` again.

3. **Fallback — LAN access** (only if the tunnel is down):

   ```powershell
   ipconfig | findstr IPv4                  # find your laptop's LAN IP
   # then restart uvicorn with --host 0.0.0.0
   netsh advfirewall firewall add rule name="FactoryOps backend" `
     dir=in action=allow protocol=TCP localport=8000
   ```

   Phone and laptop must be on the same Wi-Fi for this path. The tunnel is
   strictly preferable.

---

## 1. Where the app reads the backend URL

`app/build.gradle.kts` already defines two build-config fields per build type:

```kotlin
buildTypes {
    debug {
        buildConfigField("Boolean", "USE_MOCK_API", "true")
        buildConfigField("String",  "BASE_URL",    "\"http://10.0.2.2:8000/\"")
    }
    release {
        isMinifyEnabled = true
        ...
        buildConfigField("Boolean", "USE_MOCK_API", "false")
        buildConfigField("String",  "BASE_URL",    "\"https://api.candorfoods.in/\"")
    }
}
```

And `app/src/main/java/com/candorfoods/factoryops/di/NetworkModule.kt`
swaps the implementation per API based on that flag:

```kotlin
@Provides @Singleton
fun provideMachineApi(retrofit: Retrofit): MachineApi =
    if (BuildConfig.USE_MOCK_API) MockMachineApi()
    else retrofit.create(MachineApi::class.java)
```

So pointing the app at the Python backend = **flip `USE_MOCK_API` to `false`
and make sure `BASE_URL` points where the backend is actually listening**.

---

## 2. Pick the right `BASE_URL`

| Test target                                            | `BASE_URL`                                                 |
|--------------------------------------------------------|------------------------------------------------------------|
| **Recommended — phone / emulator / external tester via dev tunnel** | `"https://8vp3hks5-8000.inc1.devtunnels.ms/"`         |
| Android emulator hitting localhost directly (no tunnel) | `"http://10.0.2.2:8000/"`                                 |
| Physical phone on the same Wi-Fi (no tunnel)            | `"http://192.168.1.170:8000/"` (your LAN IP)              |
| Production                                              | `"https://api.candorfoods.in/"` (release default)         |

Trailing `/` is mandatory — Retrofit's `baseUrl()` requires it.

> `10.0.2.2` is the emulator's magic loopback alias for the host machine.
> Using `127.0.0.1` from the phone will resolve to the phone itself, not your
> laptop, and the request will fail.
>
> The dev tunnel is HTTPS, so you can skip the cleartext `network_security_config.xml`
> step below.

---

## 3. Flip the flag for debug builds

Edit `app/build.gradle.kts`:

```kotlin
buildTypes {
    debug {
        // hit the real backend instead of in-app mocks
        buildConfigField("Boolean", "USE_MOCK_API", "false")

        // dev tunnel — works on emulator, physical phone, and external testers
        buildConfigField("String",  "BASE_URL",    "\"https://8vp3hks5-8000.inc1.devtunnels.ms/\"")

        // Local-only alternatives (use one of these instead if the tunnel is down):
        //   emulator on this PC      → "\"http://10.0.2.2:8000/\""
        //   physical phone same Wi-Fi → "\"http://192.168.1.170:8000/\""
    }
    ...
}
```

Sync Gradle in Android Studio (the yellow banner), then rebuild:

```powershell
cd "d:\Maintenance module\FactoryOps"
.\gradlew :app:assembleDebug
```

Or click **Run ▶** on the `app` configuration in Android Studio.

Because `BuildConfig` is generated at compile time, **you must do a full
rebuild after editing `build.gradle.kts`** — not just press Run.

---

## 4. Cleartext HTTP — only if you fall back to LAN

> **Skip this whole section if you're using the dev tunnel** — it serves
> HTTPS, so Android's default network-security policy already allows it.

Retrofit/OkHttp on Android 9+ blocks plaintext HTTP by default. For debug
builds against a `http://10.0.2.2:8000/` or `http://192.168.x.x:8000/` URL
you need to allow cleartext for those hosts.

If `app/src/main/AndroidManifest.xml` doesn't already reference it, add:

```xml
<application
    android:networkSecurityConfig="@xml/network_security_config"
    ...>
```

And create `app/src/main/res/xml/network_security_config.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <!-- emulator host alias -->
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="true">10.0.2.2</domain>
        <!-- your laptop's LAN IP, edit to match `ipconfig` output -->
        <domain includeSubdomains="true">192.168.1.170</domain>
    </domain-config>
</network-security-config>
```

This only loosens the policy for those exact hosts. Release builds keep
the strict default (HTTPS only) because they point at `api.candorfoods.in`.

---

## 5. Log in

Use one of the seeded accounts:

| Username     | Password  | Role       |
|--------------|-----------|------------|
| `operator1`  | `pass123` | OPERATOR   |
| `operator2`  | `pass123` | OPERATOR   |
| `technician1`| `pass123` | TECHNICIAN |

`LoginViewModel` → `LoginUseCase` → `AuthRepository` → `POST /auth/login`
returns a JWT, which `AuthPreferences` persists in
`EncryptedSharedPreferences`. Subsequent calls attach the token via the
`@Header("Authorization")` parameter on each `*Api` interface
(see e.g. [`MachineApi.kt`](../FactoryOps/app/src/main/java/com/candorfoods/factoryops/data/remote/api/MachineApi.kt)).

---

## 6. Endpoint ↔ Kotlin contract map

The Python backend mirrors the existing Kotlin DTOs 1:1 — same field names
(snake_case via `@SerialName`), same enum strings, same epoch-ms timestamps.
**Do not edit the Kotlin DTOs** to match the backend; the backend was built
to match the DTOs.

| Backend handler                                                     | Kotlin caller                                                              |
|---------------------------------------------------------------------|----------------------------------------------------------------------------|
| `POST /auth/login`                                                  | `data/remote/api/AuthApi.kt` → `AuthDtos.LoginRequest/Response`            |
| `GET  /machines/assigned`                                           | `data/remote/api/MachineApi.kt` → `domain/model/Machine.kt`                |
| `POST /energy/runs/start`                                           | `data/remote/api/EnergyApi.kt` → `EnergyDtos.RunStartRequest/Response`     |
| `POST /energy/runs/{run_id}/stop`                                   | `data/remote/api/EnergyApi.kt` → `EnergyDtos.RunStopRequest/Response`      |
| `GET  /energy/machines/{id}/history?from&to`                        | `data/remote/api/EnergyApi.kt`                                             |
| `POST /breakdowns/flag`                                             | `data/remote/api/BreakdownApi.kt` → `BreakdownDtos.FlagRaiseRequest`       |
| `GET  /breakdowns?plant_id=…&since=…`                               | `data/remote/api/BreakdownApi.kt`                                          |
| `POST /breakdowns/{flag_id}/acknowledge`                            | `data/remote/api/BreakdownApi.kt`                                          |
| `POST /breakdowns/{flag_id}/resolve`                                | `data/remote/api/BreakdownApi.kt`                                          |

Enum strings match `domain/model/Enums.kt` exactly: `ROASTER`, `COMPRESSOR`,
`PACKING_LINE`, `CONVEYOR`, `HVAC`, `PUMP`, `OTHER`, `IDLE`, `RUNNING`,
`STOPPED`, `FLAGGED`, `A`/`B`/`C`, `ASSUMED`/`SPOT_MEASURED`/`IOT_METERED`.

---

## 7. Idempotency / offline sync

The mobile app is offline-first — every write goes through Room first, then a
WorkManager `SyncWorker` drains the queue. Retries can fire the same payload
multiple times, so both write endpoints are idempotent on the client-generated
UUIDs:

- `POST /energy/runs/start` — second call with the same `client_run_id` returns
  the originally-created `run_id` instead of inserting again.
- `POST /breakdowns/flag` — same with `client_flag_id`.
- `POST /energy/runs/{run_id}/stop` is naturally idempotent — stopping an
  already-stopped run returns the existing `computed_kwh`.

---

## 8. Smoke-test from PowerShell (no app needed)

Run these against either the local URL or the dev tunnel — both work.

```powershell
# Pick one:
$base = 'http://127.0.0.1:8000'                              # local
# $base = 'https://8vp3hks5-8000.inc1.devtunnels.ms'          # dev tunnel

# login
$body = '{"username":"operator1","password":"pass123"}'
$login = Invoke-RestMethod -Uri "$base/auth/login" -Method POST `
         -ContentType 'application/json' -Body $body
$token = $login.token
$login

# machines
Invoke-RestMethod -Uri "$base/machines/assigned" `
  -Headers @{ Authorization = "Bearer $token" } | Select-Object -First 2

# floor dashboard summary
Invoke-RestMethod -Uri "$base/floors/" `
  -Headers @{ Authorization = "Bearer $token" }
```

Or open Swagger at `https://8vp3hks5-8000.inc1.devtunnels.ms/docs` (or the
local `/docs`) and use **Authorize** to paste the token.

---

## 9. Common gotchas

| Symptom                                                                | Fix                                                                                              |
|------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| App still shows the 5 mock machines after editing `build.gradle.kts`   | Sync Gradle + clean rebuild — `BuildConfig` is regenerated only on full build.                  |
| Tunnel URL returns HTML (a "Continue to the tunnel" page) instead of JSON | Set port visibility to **Public** in VS Code → Ports panel → right-click the port → *Port Visibility → Public*. |
| Tunnel URL stopped working after a laptop reboot                       | Re-open the **Ports** panel in VS Code and forward 8000 again. If you get a different subdomain, update `BASE_URL` and rebuild. |
| Emulator can't reach `http://localhost:8000`                            | Use the dev tunnel URL, or `http://10.0.2.2:8000/` for direct local access.                     |
| Physical phone shows "Network request failed"                          | If using the tunnel: confirm tunnel is up + visibility is Public. If on LAN: Wi-Fi mismatch, firewall blocking 8000, or missing cleartext config. |
| `CLEARTEXT communication not permitted` in Logcat                      | You're using an `http://` URL — switch to the HTTPS dev tunnel, or add the host to `network_security_config.xml` (step 4). |
| Login works, every other request returns 401                           | Phone clock drift → JWT `exp` invalid. Sync system time, log in again.                           |
| `/machines/assigned` returns `[]`                                       | The seeded operator has no machine assignments → backend falls back to plant scope. Empty means seed didn't run — re-run `python -m scripts.seed`. |
| Retrofit converter error on enums                                       | Enum values from the backend are uppercase strings (`"RUNNING"`); the Kotlin DTOs use `@SerialName("RUNNING")`. Don't switch the converter to camel-case. |
| `current_status` doesn't change after start/stop                       | The app reads from Room; the new value arrives on the next `getAssignedMachines()` pull or pull-to-refresh on Home. |

---

## 10. Going to production

1. **Database** — set `DATABASE_URL=postgresql+psycopg://…` in `backend/.env`
   and `pip install psycopg[binary]`. SQLAlchemy models are unchanged.
2. **Secrets** — strong `JWT_SECRET`, remove `DEV_BYPASS_TOKEN` from `.env`.
3. **HTTPS** — put the FastAPI app behind nginx or Caddy with a real certificate.
   The release `BASE_URL` already uses `https://`.
4. **Release APK** — `gradlew :app:assembleRelease`. The release build flips
   `USE_MOCK_API=false` and points at `https://api.candorfoods.in/` already.
5. **Real FCM project** — replace `app/google-services.json` and remove the
   FCM placeholder code in `notification/FcmService.kt`.
