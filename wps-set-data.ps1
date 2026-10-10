$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Kwps.Application')
$d=$w.ActiveDocument
$src=$w.Documents.Item(2)
$x=$src.OMaths.Item($src.OMaths.Count).Range.WordOpenXML
$m=$w.Run('XformOMML2MML',$x)
$s=$d.InlineShapes.Item(3)
$s.Range.Select()
Write-Output ('SetData='+$w.Run('SetMTData',$s,$m))