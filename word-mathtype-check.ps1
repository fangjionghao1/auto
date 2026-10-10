$ErrorActionPreference='Stop'
$w=New-Object -ComObject Word.Application
$w.Visible=$false
Write-Output ('WordVersion='+$w.Version+' Path='+$w.Path)
foreach($a in $w.AddIns){Write-Output ($a.Name+' Installed='+$a.Installed)}
