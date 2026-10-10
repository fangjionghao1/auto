$ErrorActionPreference='Stop'
$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Kwps.Application')
$d=$w.ActiveDocument
if($d.FullName -ne 'D:\wkplace\auto\mathtype-conversion-working.docx'){throw 'Wrong document'}
$d.Close(0)
$d=$w.Documents.Open('D:\wkplace\auto\mathtype-conversion-working.docx')
$d.Activate()
$w.Run('IsDLLVersionOK')
$r=$d.OMaths.Item($d.OMaths.Count).Range
$m=$w.Run('XformOMML2MML',$r.WordOpenXML)
$pos=$r.Start
$r.Delete() | Out-Null
$r=$d.Range($pos,$pos)
$r.InsertFile('D:\math\anzhuang\Office Support\BlankEqn.doc','MTBlankEqn')
$s=$null
foreach($a in $d.InlineShapes){if($a.Type -eq 1 -and $a.Range.Start -eq $pos){$s=$a;break}}
if($null -eq $s){throw 'Inserted object not found'}
$s.Range.Select()
Write-Output ('SetData='+$w.Run('SetMTData',$s,$m))
Write-Output ('Remaining='+$d.OMaths.Count+' Shapes='+$d.InlineShapes.Count+' Position='+$pos)