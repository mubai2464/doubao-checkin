# 豆包每日自动签到（GitHub Actions版）

每天北京时间 9:00 自动在豆包 agent-explore 页面签到，不需要本地电脑开机。

## 部署步骤

### 1. 创建 GitHub 仓库
- 登录 GitHub，新建一个 **Private** 仓库（命名随意，如 `doubao-checkin`）
- 不要用 Public 仓库，登录态虽然存在 Secret 里，但仓库本身应保持私有

### 2. 上传文件
把本项目下的所有文件上传到仓库根目录：
```
checkin.py
requirements.txt
.github/workflows/checkin.yml
```

### 3. 配置 Secret（关键步骤）
- 仓库页面 → **Settings** → **Secrets and variables** → **Actions**
- 点击 **New repository secret**
- Name 填：`STORAGE_STATE_B64`
- Secret 内容：打开同目录下的 `storage_state_b64.txt`，**全部复制**粘贴进去
- 点击 Add secret

### 4. 手动测试一次
- 仓库页面 → **Actions** 标签
- 左侧选择 **Doubao Daily Checkin**
- 点击 **Run workflow** 按钮 → 选择分支 → 点击绿色 Run workflow
- 等1-2分钟，点进去看日志是否显示"签到成功"

### 5. 完成
之后每天北京时间 9:00 会自动运行，无需任何操作。

## 注意事项

### 登录态有效期
- Cookie 有效期约 29 天，签到成功会自动续期
- 如果某天日志显示"登录态已失效"，需要重新导出 storage_state 并更新 Secret

### 异地登录风控
- GitHub Actions 的运行 IP 在美国，豆包可能判定为异常登录
- 如果遇到要求短信验证，此方案会失败
- 失败时 Actions 会标红，截图会作为 Artifact 保存（可在运行记录中下载）

### 免费额度
- 私有仓库每月 2000 分钟免费额度
- 每次签到约耗时 1-2 分钟，每月最多 60 分钟，完全够用

## 重新导出登录态（cookie过期时）
在本地电脑运行：
```powershell
# 在本项目的 doubao_daily_checkin.py 所在目录
python doubao_daily_checkin.py --setup
# 登录成功后，运行导出脚本
python _export_state.py
# 然后把 storage_state.json 转 base64，更新 GitHub Secret
```
