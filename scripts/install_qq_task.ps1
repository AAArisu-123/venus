# Register this project's QQ bot under the signed-in Windows user, without credentials.
$ErrorActionPreference = 'Stop'
$name = 'Venus QQ'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $root '.env') -PathType Leaf)) {
    throw 'Venus virtual environment or local .env is missing.'
}
if (Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue) {
    throw 'The Venus QQ task already exists. This installer will not overwrite it.'
}
$running = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -in 'python.exe','pythonw.exe' -and
    $_.CommandLine -match '(?:^|\s)-m\s+venus\.qq_(?:bot|service)(?:\s|$)'
}
if ($running) { throw 'Stop the existing Venus QQ process before enabling the task.' }
$userId = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$logon = New-ScheduledTaskTrigger -AtLogOn -User $userId
# The indefinite periodic trigger gets another attempt if the restart budget is exhausted.
$retry = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
$retry.Repetition.StopAtDurationEnd = $false
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 8
$action = New-ScheduledTaskAction -Execute $python -Argument '-m venus.qq_service' -WorkingDirectory $root
Register-ScheduledTask -TaskName $name -TaskPath '\' -Action $action -Principal $principal `
    -Trigger @($logon, $retry) -Settings $settings -Description 'Venus QQ bot; user logon and automatic recovery.' | Out-Null
Start-ScheduledTask -TaskName $name -TaskPath '\'
