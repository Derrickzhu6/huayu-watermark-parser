# 桦煜去水印

## 功能
- 🔗 **短视频链接解析**：支持抖音、B站链接去水印
- 🖼 **图片去水印**：一键自动去水印 + 涂抹修复
- 🔄 **格式转换**：图片、视频、音频、文件格式互转

## 技术栈
- 后端：Python + 内置 HTTP 服务器
- 前端：HTML + CSS + JavaScript（单页应用）
- 视频解析：yt-dlp + Playwright（抖音免Cookie）

---

# 📦 微信小程序完整上架流程

## 第1步：购买服务器（最便宜的方案）

### 方案一：腾讯云轻量服务器（推荐）
- **价格**：¥24/月（2核2G 40G SSD）
- **链接**：https://curl.qcloud.com/ 搜索"轻量应用服务器"
- **选择**：CentOS 7.9 或 Ubuntu 22.04

### 方案二：阿里云轻量服务器
- **价格**：¥24/月（2核2G 40G SSD）
- **链接**：https://www.aliyun.com/ 搜索"轻量应用服务器"

### 方案三：搬瓦工（国外，免备案）
- **价格**：$49.99/年（约¥30/月）
- **链接**：https://bwh81.net/

> 💡 建议选腾讯云¥24/月的轻量服务器，国内访问速度快

## 第2步：服务器初始化

### 购买服务器后：
1. 重置密码，用 SSH 登录服务器
2. 安装宝塔面板（可视化操作，适合新手）：
   ```bash
   wget -O install.sh https://download.bt.cn/install/install-ubuntu.sh && bash install.sh
   ```
3. 在宝塔面板中安装：Nginx + Python 项目管理器

### 或者用一键脚本：
```bash
# 上传项目文件到服务器后运行：
bash deploy.sh
```

## 第3步：配置域名

1. 购买域名（腾讯云/阿里云约¥30-50/年）
2. 域名解析 → 添加 A 记录 → 指向你的服务器IP
3. 在宝塔面板中配置 Nginx 反向代理 + 申请免费 SSL 证书

## 第4步：注册微信小程序

1. 打开 https://mp.weixin.qq.com/ → 注册
2. 选择"小程序"类型
3. 个人开发者注册费 ¥300/年
4. 注册完成后，在"开发"→"开发设置"中获取 AppID
5. 在"开发"→"服务器域名"中添加你的域名

## 第5步：小程序代码

项目中的 `miniprogram/` 目录有微信小程序脚手架代码。
需要在微信开发者工具中编辑：
1. 下载微信开发者工具
2. 打开 miniprogram 目录
3. 修改 app.js 中的 serverUrl 为你的服务器地址
4. 提交审核

## 第6步：审核上架

1. 在微信开发者工具中上传代码
2. 登录 mp.weixin.qq.com → 版本管理 → 提交审核
3. 审核通过后发布

---

## 本地开发

### 启动服务
```bash
cd C:\AI_Workspace\01_Projects\视频解析API
python fast_server.py
```

### 访问地址
http://localhost:8000/


---

# ☁ 微信云托管部署

## 前置条件
1. 开通微信云开发：https://console.cloud.tencent.com/tcb
2. 创建环境（选择"按量计费"，免费额度够用）
3. 在环境设置中获取 `环境ID`

## 部署步骤

### 第1步：开通云托管
1. 打开云开发控制台 → 云托管 → 立即开通
2. 选择"按量计费"模式

### 第2步：修改配置
1. 打开 `cloudbaserc.json`，把 `envId` 改成你的环境ID
2. 打开 `miniprogram/app.js`，把 `serverUrl` 改成云托管分配的域名

### 第3步：上传部署
```bash
# 安装 CloudBase CLI
npm install -g @cloudbase/cli

# 登录
cloudbase login

# 部署
cloudbase framework deploy
```

### 第4步：配置小程序
1. 在云托管控制台获取服务域名（如 `https://xxx-xxx.service.tcloudbase.com`）
2. 打开微信小程序后台 → 开发 → 开发设置 → 服务器域名
3. 把云托管域名添加到 `request合法域名`
4. 修改 `miniprogram/app.js` 中的 `serverUrl`

### 第5步：提交小程序审核
1. 微信开发者工具上传代码
2. 微信公众平台提交审核
