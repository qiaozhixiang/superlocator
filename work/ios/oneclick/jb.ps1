# 一键越狱 / 一键装插件（Windows）
#
# 用法（PowerShell，右键“以管理员身份运行”）：
#   .\jb.ps1                 # 检测 + 打印方案
#   .\jb.ps1 -Run            # 真的执行：装依赖、推装越狱 App / 引导 palera1n
#   .\jb.ps1 -Deb .\LocSim.deb   # 越狱后顺带装插件
#
# 说明：checkm8 机型（iPhone 6s~X）进 DFU 必须人工按键，软件无法代按；
#       其余步骤（下载、推装、装插件、写配置、重启桌面）都能一键跑完。

param(
    [switch]$Run,
    [string]$Deb = "",
    [string]$Ipa = ""
)

$ErrorActionPreference = "Stop"
function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Die($m) { Write-Host "[x] $m" -ForegroundColor Red; exit 1 }
function Do-Run([string]$exe, [string[]]$argv) {
    if ($Run) { Say ("执行: {0} {1}" -f $exe, ($argv -join " ")); & $exe @argv }
    else { Write-Host ("    (dry) {0} {1}" -f $exe, ($argv -join " ")) }
}

# ---------- 0. 环境 ----------
Say "检查环境"
$svc = Get-Service -Name "Apple Mobile Device Service" -ErrorAction SilentlyContinue
if (-not $svc) { Warn "没装 Apple Mobile Device Service（装 Apple Devices 或 iTunes：winget install --id Apple.AppleDevices -e）" }
else { Say "苹果驱动服务存在：$($svc.Status)" }

$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Die "缺 python：winget install --id Python.Python.3.12 -e，装完重开一个窗口" }
if ($Run) {
    & $py.Source -m pip install --upgrade pymobiledevice3 | Out-Null
    Say "pymobiledevice3 已就绪"
}

# ---------- 1. 读设备 ----------
Say "读取已连接的 iPhone"
$raw = ""
try { $raw = (& $py.Source -m pymobiledevice3 usbmux list 2>$null) -join "`n" } catch { $raw = "" }
$model = [regex]::Match($raw, '"ProductType"\s*:\s*"([^"]+)"').Groups[1].Value
$ver = [regex]::Match($raw, '"ProductVersion"\s*:\s*"([^"]+)"').Groups[1].Value
$udid = [regex]::Match($raw, '"UniqueDeviceID"\s*:\s*"([^"]+)"').Groups[1].Value

if (-not $model) {
    Warn "自动识别失败，手动输入："
    $model = Read-Host "  机型（如 iPhone12,1）"
    $ver = Read-Host "  系统版本（如 16.6.1）"
}
Say ("机型 {0} · 系统 {1} · UDID {2}" -f $model, $ver, $(if ($udid) { $udid } else { "未读到" }))

# ---------- 2. 判定 ----------
$checkm8 = $model -match '^iPhone(8|9),' -or $model -match '^iPhone10,[1-6]$' -or $model -match '^iPhone10,3$' -or $model -match '^iPhone10,6$'
$parts = $ver.Split(".")
$maj = [int]$parts[0]; $min = if ($parts.Length -gt 1) { [int]$parts[1] } else { 0 }

if ($checkm8) { $tool = "palera1n" }
elseif ($maj -lt 16 -or ($maj -eq 16 -and $min -le 6)) { $tool = "dopamine" }
elseif ($maj -eq 17 -and $min -eq 0) { $tool = "trollfools" }
else { $tool = "box" }

switch ($tool) {
    "palera1n" { Say "方案：palera1n（checkm8，rootless）" }
    "dopamine" { Say "方案：Dopamine（手机上点一下就完成越狱）" }
    "trollfools" { Say "方案：TrollStore + TrollFools（不越狱，按 App 注入）" }
    "box" { Say "方案：没有公开越狱 → 走『定位盒子』" }
}

# ---------- 3. 执行 ----------
switch ($tool) {
    "dopamine" {
        $url = "https://github.com/opa334/Dopamine/releases/latest/download/Dopamine.tipa"
        $out = Join-Path $env:TEMP "Dopamine.tipa"
        if ($Run) {
            Say "下载 Dopamine.tipa"
            Invoke-WebRequest -Uri $url -OutFile $out
            Say "推装到手机"
            Do-Run $py.Source @("-m", "pymobiledevice3", "apps", "install", $out)
            Say "现在在手机上：打开 Dopamine → 点 Jailbreak → 等重启 → 出现 Sileo"
        } else {
            Write-Host ("    下载: {0}" -f $url)
        }
    }
    "palera1n" {
        Warn "checkm8 机型需要人工进 DFU（音量下 + 电源，按提示松手）"
        $wsl = (Get-Command wsl -ErrorAction SilentlyContinue)
        if (-not $wsl) {
            Warn "没装 WSL2。装一次：wsl --install -d Ubuntu，然后重跑本脚本"
        } else {
            if ($Run) { Do-Run "wsl" @("-d", "Ubuntu", "--", "sudo", "palera1n", "-l") }
            else { Write-Host '    (dry) wsl -d Ubuntu -- sudo palera1n -l' }
        }
    }
    "trollfools" {
        Write-Host "    1) 装 TrollStore：https://github.com/opa334/TrollStore/releases"
        Write-Host "    2) 装 TrollFools，选目标 App，注入我们的 LocSim.dylib"
    }
    "box" {
        Write-Host "    这台机器只能配盒子（work/ios/ONDEVICE.md 形态三）"
        exit 0
    }
}

# ---------- 4. 插件 / App ----------
if ($Deb) {
    if (-not (Test-Path $Deb)) { Die "找不到 $Deb" }
    Warn "deb 需要手机开 SSH（越狱后默认 root/alpine），两条命令最快："
    Write-Host ("   scp '{0}' root@<手机IP>:/var/mobile/" -f (Resolve-Path $Deb))
    Write-Host '   ssh root@<手机IP> "dpkg -i /var/mobile/LocSim.deb && killall -9 SpringBoard"'
}
if ($Ipa) {
    if (-not (Test-Path $Ipa)) { Die "找不到 $Ipa" }
    Do-Run $py.Source @("-m", "pymobiledevice3", "apps", "install", (Resolve-Path $Ipa))
}

Say "完成。关闭虚拟定位：把 com.stv.locsim.plist 里 enabled 改 false 再重载。"