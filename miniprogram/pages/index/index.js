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
    wx.showLoading({ title: "下载中..." });
    wx.downloadFile({
      url: r.video_url,
      success: (res) => {
        wx.saveVideoToPhotosAlbum({
          filePath: res.tempFilePath,
          success: () => { wx.showToast({ title: "已保存到相册" }); },
          fail: () => { wx.showToast({ title: "保存失败，请授权相册权限", icon: "none" }); }
        });
      },
      fail: () => {
        // 不支持直接下载，用分享
        wx.showToast({ title: "下载失败，请长按视频保存", icon: "none" });
      },
      complete: () => { wx.hideLoading(); }
    });
  }
});
