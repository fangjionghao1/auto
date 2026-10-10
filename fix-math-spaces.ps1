$ErrorActionPreference='Stop'
$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Kwps.Application')
$d=$null
foreach($dd in $w.Documents){if($dd.FullName -eq 'D:\wkplace\auto\mathtype-conversion-working.docx'){$d=$dd}}
if(!$d){throw 'Working document not open'}
$d.Activate()
$w.Run('IsDLLVersionOK') | Out-Null
$eqs=@(); for($i=1;$i -le $d.InlineShapes.Count;$i++){$a=$d.InlineShapes.Item($i); if($a.Type -eq 1){$eqs+=,$a}}; Write-Output ('Mapped='+$eqs.Count)
$a=Get-Content 'D:\wkplace\auto\equation-audit.json' -Raw -Encoding UTF8 | ConvertFrom-Json
if($eqs.Count -ne $a.Count){throw 'Mapping mismatch'}
$fixed=0
foreach($e in $a){
 $m=$e.mml
 $m=[regex]::Replace($m,'<mml:(mi|mo|mtext)(?:\s[^>]*)?>\s+</mml:\1>','<mml:mspace width="0.167em"/>')
 if($m -ne $e.mml){
  $s=$eqs[$e.index-1]
  $s.Range.Select()
  if(!$w.Run('SetMTData',$s,$m)){throw ('Failed equation '+$e.index)}
  $fixed++
  Write-Output ('Fixed equation '+$e.index)
 }
}
Write-Output ('Fixed='+$fixed+' OMML='+$d.OMaths.Count+' OLE='+$eqs.Count)
$d.ExportAsFixedFormat('D:\wkplace\auto\equations-fixed-qa.pdf',17)