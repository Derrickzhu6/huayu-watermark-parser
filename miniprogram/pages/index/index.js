const app = getApp();
Page({
  data: { url: "", loading: false, result: null, error: "" },
  
  onInput(e) { this.setData({ url: e.detail.value }); },
  
  onParse() {
    const url = this.data.url.trim();
    if (!url) { wx.showToast({ title: "请输入链接", icon: "none" }); return; }
    this.setData({ loading: true, result: null, error: "" });
    
    wx.request({
      url: app.globalData.serverUrl + "/api/video/parse",
      method: "POST",
      header: { "Content-Type": "application/x-www-form-urlencoded" },
      data: "url=" + encodeURIComponent(url),
      timeout: 30000,
      success: (res) => {
        if (res.data.success) {
          this.setData({ result: res.data, error: "" });
        } else {
          wx.showToast({ title: res.data.error || "解析失败", icon: "none" });
        }
      },
      fail: (err) => {
        wx.showToast({ title: "网络错误，请检查服务器", icon: "none" });
      },
      complete: () => { this.setData({ loading: false }); }
    });
  },
  
  onDownload() {
    const r = this.data.result;
    if (!r || !r.video_url) return;
    const app = getApp();
    wx.showLoading({ title: "下载中..." });
    // 通过服务器代理下载（解决小程序无法直接下载第三方CDN资源）
    wx.request({
      url: app.globalData.serverUrl + "/api/video/download",
      method: "POST",
      header: { "Content-Type": "application/x-www-form-urlencoded" },
      data: "url=" + encodeURIComponent(r.video_url),
      timeout: 60000,
      success: (res) => {
        if (res.data.path) {
          const dlUrl = app.globalData.serverUrl + res.data.path;
          wx.downloadFile({
            url: dlUrl,
            success: (dlRes) => {
              wx.saveVideoToPhotosAlbum({
                filePath: dlRes.tempFilePath,
                success: () => { wx.showToast({ title: "已保存到相册" }); },
                fail: () => { wx.showToast({ title: "保存失败，请授权相册权限", icon: "none" }); }
              });
            },
            fail: () => { wx.showToast({ title: "下载失败", icon: "none" }); }
          });
        } else {
          wx.showToast({ title: res.data.error || "下载失败", icon: "none" });
        }
      },
      fail: () => { wx.showToast({ title: "网络错误", icon: "none" }); },
      complete: () => { wx.hideLoading(); }
    });
  }
});
