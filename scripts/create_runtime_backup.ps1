param(
  [string]$BackupRoot = "D:\ASSAM_JOB_DATA\backups",
  [string]$RawRoot = "D:\ASSAM_JOB_DATA\raw"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

if ([string]::IsNullOrWhiteSpace($env:AJI_BACKUP_DATABASE_URL)) {
  throw "AJI_BACKUP_DATABASE_URL is required."
}
if (-not (Test-Path -LiteralPath $RawRoot -PathType Container)) {
  throw "The external raw-storage root does not exist."
}

$stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss")
$destination = Join-Path $BackupRoot $stamp
$rawDestination = Join-Path $destination "raw"
New-Item -ItemType Directory -Path $rawDestination -Force | Out-Null
$dumpPath = Join-Path $destination "assam-job-intelligence.dump"
$pgDatabaseUrl = $env:AJI_BACKUP_DATABASE_URL -replace '^postgresql\+psycopg://', 'postgresql://'

$pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if ($null -ne $pgDump) {
  & $pgDump.Source --format=custom --file=$dumpPath $pgDatabaseUrl
}
else {
  $dockerDatabaseUrl = $pgDatabaseUrl `
    -replace '@localhost:', '@host.docker.internal:' `
    -replace '@127\.0\.0\.1:', '@host.docker.internal:'
  if ($env:GITHUB_ACTIONS) {
    Write-Output "::add-mask::$dockerDatabaseUrl"
  }
  docker run --rm `
    --volume "${destination}:/backup" `
    postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73 `
    pg_dump --format=custom --file=/backup/assam-job-intelligence.dump $dockerDatabaseUrl
}
Get-ChildItem -LiteralPath $RawRoot -Force |
  Copy-Item -Destination $rawDestination -Recurse -Force

$manifest = [ordered]@{
  created_at = [DateTimeOffset]::UtcNow.ToString("o")
  database_dump = $dumpPath
  database_sha256 = (Get-FileHash -LiteralPath $dumpPath -Algorithm SHA256).Hash.ToLowerInvariant()
  raw_snapshot = $rawDestination
  repository = $env:GITHUB_REPOSITORY
  commit = $env:GITHUB_SHA
  workflow_run_id = $env:GITHUB_RUN_ID
}
$manifestPath = Join-Path $destination "manifest.json"
$manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8
if ($env:GITHUB_OUTPUT) {
  "backup_manifest=$manifestPath" | Out-File $env:GITHUB_OUTPUT -Append -Encoding utf8
}
Write-Output "Coordinated runtime backup created: $manifestPath"
