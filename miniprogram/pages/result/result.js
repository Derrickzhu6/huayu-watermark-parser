const app = getApp();
Page({
  data: { serverUrl: app.globalData.serverUrl },

  copyLink() {
    wx.setClipboardData({ data: this.data.serverUrl });
  },

  onAbout() {
    wx.showModal({
      title: "关于桦煜去水印",
      content: "桦煜去水印是一款免费的在线去水印工具，支持抖音、B站等平台的视频链接去水印，以及图片去水印和格式转换功能。",
      showCancel: false
    });
  },

  onPrivacy() {
    wx.showModal({
      title: "隐私说明",
      content: "1. 所有处理均在服务端完成
2. 上传文件处理完成后自动删除
3. 不会收集任何个人信息
4. 不存储用户任何数据",
      showCancel: false
    });
  }
});
