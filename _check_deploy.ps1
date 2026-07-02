try {
    $r = Invoke-WebRequest -Uri 'https://geocon-dash-516554645957.australia-southeast1.run.app/' -UseBasicParsing -TimeoutSec 15
    $content = $r.Content
    $hasGold = $content.Contains('C8A55B')
    $hasLogo = $content.Contains('topbar-logo')
    $hasBrand = $content.Contains('brand-primary')
    $result = "HTTP Status: $($r.StatusCode)`nContent length: $($content.Length)`nHas gold (#C8A55B): $hasGold`nHas topbar-logo: $hasLogo`nHas brand-primary: $hasBrand`n`nFirst 300 chars:`n$($content.Substring(0, [Math]::Min(300, $content.Length)))"
    [System.IO.File]::WriteAllText('c:\Users\DELL\bidbrain-analytics\_deploy_result.txt', $result)
} catch {
    [System.IO.File]::WriteAllText('c:\Users\DELL\bidbrain-analytics\_deploy_result.txt', "ERROR: $($_.Exception.Message)")
}