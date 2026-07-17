# Cookie 导入操作文档

## 为什么需要 Cookie？

抖音对未登录访问有严格限制，携带有效的登录 Cookie 可以：
- 解决 "Fresh cookies are needed" 错误
- 提高解析成功率
- 避免 403/429 拦截

## 导出 Cookie 方法

### Chrome 浏览器（推荐）

1. 安装 EditThisCookie 扩展
   - Chrome Web Store 搜索 "EditThisCookie"
   - 或者访问: https://chrome.google.com/webstore/detail/editthiscookie/fngmhnnpilhplaeedifhccceomclgfbg

2. 登录抖音网页版
   - 访问 https://www.douyin.com
   - 扫码登录你的抖音账号

3. 导出 Cookie
   - 点击 EditThisCookie 图标
   - 点击 "Export" 按钮
   - 选择 "Netscape HTTP Cookie File" 格式
   - 保存为 cookies.txt

### Edge 浏览器

1. 安装 Cookie-Editor 扩展
2. 登录 https://www.douyin.com
3. 点击 Cookie-Editor 图标 → Export → Netscape 格式

### Firefox 浏览器

1. 安装 Cookies.txt 扩展
2. 登录 https://www.douyin.com
3. 点击 Cookies.txt 图标 → Export

## 导入 Cookie

### 方式一：通过 API 导入（推荐）

```bash
curl -X POST http://localhost:8000/api/cookie/import \
  -F "file=@/path/to/cookies.txt"
```

### 方式二：通过命令行脚本导入

```bash
python generate_cookies.py --import /path/to/cookies.txt
```

### 方式三：手动编辑 Cookie 池文件

编辑 `processors/cookies/cookies_pool.txt`，按 Netscape 格式添加 Cookie。

## 验证 Cookie 状态

```bash
curl http://localhost:8000/api/cookie/status
```

成功响应示例：
```json
{
  "success": true,
  "data": {
    "total_groups": 2,
    "failed_groups": 0,
    "current_index": 0,
    "has_expired": false,
    "expired_count": 0
  }
}
```

## Cookie 格式说明

Netscape Cookie 格式每行包含 7 个字段，以 Tab 分隔：

```
Domain    IncludeSubdomains    Path    Secure    Expires    Key    Value
```

示例：
```
.douyin.com	TRUE	/	FALSE	1893456000	sessionid	your_session_value
```

字段说明：
- **Domain**: Cookie 所属域名（前面加点表示匹配所有子域名）
- **IncludeSubdomains**: TRUE/FALSE 是否包含子域名
- **Path**: Cookie 路径，一般为 /
- **Secure**: TRUE/FALSE 是否仅 HTTPS
- **Expires**: 过期时间戳（秒），0 表示会话 Cookie
- **Key**: Cookie 名称
- **Value**: Cookie 值

## 常见问题

### Q: Cookie 多久过期？
A: 抖音 Cookie 一般有效期为 1-7 天。过期后 API 会自动检测并切换到备用 Cookie。

### Q: 需要多少组 Cookie？
A: 建议准备 3-5 组不同账号的 Cookie，轮换使用效果最好。

### Q: Cookie 泄露风险？
A: Cookie 包含登录态，请妥善保管。不要在公共网络传输。建议使用专门的解析账号。
