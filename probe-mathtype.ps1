Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class MTProbe { [DllImport(@"D:\math\anzhuang\MathPage\32\MathPage.wll")] public static extern int MTInitAPI(short options,short timeout); [DllImport(@"D:\math\anzhuang\MathPage\32\MathPage.wll")] public static extern int MTXFormReset(); [DllImport(@"D:\math\anzhuang\MathPage\32\MathPage.wll")] public static extern int MTTermAPI(); }'
Write-Output ('Init=' + [MTProbe]::MTInitAPI(0,10))
Write-Output ('Reset=' + [MTProbe]::MTXFormReset())
Write-Output ('Term=' + [MTProbe]::MTTermAPI())
