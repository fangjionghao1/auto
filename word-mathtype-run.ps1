$ErrorActionPreference='Stop'
$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application')
$d=$w.ActiveDocument
Write-Output ('Document='+$d.Name+' Before='+$d.OMaths.Count)
$flags=[Reflection.BindingFlags]::InvokeMethod
Write-Output ('Init='+$w.GetType().InvokeMember('Run',$flags,$null,$w,@('IsDLLVersionOK')))
$w.GetType().InvokeMember('Run',$flags,$null,$w,@('DoConvertEquations',$false,8,$false,$false,'',0,0))
Write-Output ('After='+$d.OMaths.Count+' InlineShapes='+$d.InlineShapes.Count)