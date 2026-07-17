const app = getApp();
Page({
  data: { serverUrl: app.globalData.serverUrl },

  copyLink() {
    wx.setClipboardData({ data: this.data.serverUrl });
    wx.showToast({ title: "已复制", icon: "success" });
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
      content: "1. 所有处理均在服务端完成\n2. 上传文件处理完成后自动删除\n3. 不会收集任何个人信息\n4. 不存储用户任何数据",
      showCancel: false
    });
  },

  onFeedback() {
    wx.showModal({
      title: "意见反馈",
      content: "如需反馈问题或建议，请发送邮件至：huayu@example.com",
      confirmText: "复制邮箱",
      success: (res) => {
        if (res.confirm) {
          wx.setClipboardData({ data: "huayu@example.com" });
          wx.showToast({ title: "邮箱已复制", icon: "success" });
        }
      }
    });
  }
});
