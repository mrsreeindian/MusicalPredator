Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { 
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
}
function AwaitOp($op, $type) {
    $m = $asTaskGeneric.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.Wait()
    return $t.Result
}
try {
    $asyncOp = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media, ContentType = WindowsRuntime]::RequestAsync()
    $mgr = AwaitOp $asyncOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
    $session = $mgr.GetCurrentSession()
    if ($session) {
        $props = AwaitOp ($session.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
        $outObj = @{
            Title = $props.Title
            Artist = $props.Artist
            AlbumTitle = $props.AlbumTitle
            HasThumbnail = ($props.Thumbnail -ne $null)
        }
        $targetDir = $args[0]
        if ($props.Thumbnail -and $targetDir) {
            $stream = AwaitOp ($props.Thumbnail.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
            $asStreamMethod = [System.IO.WindowsRuntimeStreamExtensions].GetMethod("AsStream", [Type[]]@([Windows.Storage.Streams.IRandomAccessStream]))
            if ($asStreamMethod) {
                $netStream = $asStreamMethod.Invoke($null, @($stream))
                $hash = [BitConverter]::ToString([System.Security.Cryptography.MD5]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($props.Title + $props.Artist))).Replace('-', '')
                $outFile = [System.IO.Path]::Combine($targetDir, "cover_" + $hash + ".jpg")
                $fileStream = [System.IO.File]::Create($outFile)
                $netStream.CopyTo($fileStream)
                $fileStream.Close()
                $netStream.Close()
                $outObj["SavedPath"] = $outFile
            }
        }
        $outObj | ConvertTo-Json -Compress
    } else {
        '{"NoSession": true}'
    }
} catch {
    '{"Error": "' + $_.Exception.Message.Replace('"', '\"') + '"}'
}
