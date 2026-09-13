param(
  [Parameter(Mandatory = $true)][string]$Image,
  [Parameter(Mandatory = $true)][string]$BaseUrl,
  [string]$ComposeFile = "docker-compose.release.yml",
  [string]$AuditFile = "D:\ASSAM_JOB_DATA\public-release\releases.jsonl"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

if ($Image -notmatch '^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$') {
  throw "Deployment image must use an immutable GHCR sha256 digest."
}
if (-not $env:AJI_DATABASE_URL -or -not $env:AJI_PUBLIC_HOSTNAME) {
  throw "AJI_DATABASE_URL and AJI_PUBLIC_HOSTNAME are required."
}

$previousImage = ""
$existing = docker container ls -a --filter "name=^/aji-public-web$" --format '{{.Image}}'
if (-not [string]::IsNullOrWhiteSpace($existing)) {
  $previousImage = $existing.Trim()
}

$env:AJI_PUBLIC_IMAGE = $Image
$deployed = $false
try {
  docker compose -f $ComposeFile pull
  docker compose -f $ComposeFile up -d --remove-orphans

  $healthy = $false
  foreach ($attempt in 1..30) {
    $state = docker container inspect aji-public-web --format '{{.State.Health.Status}}' 2>$null
    if ($LASTEXITCODE -eq 0 -and $state.Trim() -eq "healthy") {
      $healthy = $true
      break
    }
    Start-Sleep -Seconds 2
  }
  if (-not $healthy) {
    throw "Public application did not become healthy within 60 seconds."
  }

  uv run python scripts/public_release_smoke.py --base-url $BaseUrl
  if ($LASTEXITCODE -ne 0) {
    throw "Public release smoke test failed."
  }
  $deployed = $true
}
finally {
  if (-not $deployed) {
    if ($previousImage) {
      $env:AJI_PUBLIC_IMAGE = $previousImage
      docker compose -f $ComposeFile up -d --force-recreate public-web
    }
    else {
      docker compose -f $ComposeFile stop public-web
    }
  }
}

$auditDirectory = Split-Path -Parent $AuditFile
New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
$event = [ordered]@{
  deployed_at = [DateTimeOffset]::UtcNow.ToString("o")
  image = $Image
  previous_image = if ($previousImage) { $previousImage } else { $null }
  repository = $env:GITHUB_REPOSITORY
  workflow_run_id = $env:GITHUB_RUN_ID
  actor = $env:GITHUB_ACTOR
  result = "DEPLOYED"
}
Add-Content -LiteralPath $AuditFile -Value ($event | ConvertTo-Json -Compress) -Encoding utf8
if ($env:GITHUB_OUTPUT) {
  "previous_image=$previousImage" | Out-File $env:GITHUB_OUTPUT -Append -Encoding utf8
  "deployed_image=$Image" | Out-File $env:GITHUB_OUTPUT -Append -Encoding utf8
}
Write-Output "Public release deployed and smoke-tested: $Image"
