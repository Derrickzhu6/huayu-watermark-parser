const app = getApp();

const FORMAT_MAP = {
  image: ['jpg', 'png', 'webp', 'bmp', 'gif', 'tiff'],
  video: ['mp4', 'avi', 'mov', 'mkv', 'webm'],
  audio: ['mp3', 'wav', 'aac', 'ogg', 'flac'],
  file: ['txt', 'pdf', 'docx', 'xlsx']
};

Page({
  data: { type: 'image', formats: FORMAT_MAP.image, targetFormat: '', filePath: '', fileName: '', loading: false, resultUrl: '', resultName: '' },

  switchType(e) {
    const type = e.currentTarget.dataset.type;
    this.setData({ type, formats: FORMAT_MAP[type], targetFormat: '', filePath: '', fileName: '', resultUrl: '', resultName: '' });
  },

  onFormatChange(e) {
    this.setData({ targetFormat: this.data.formats[e.detail.value] });
  },

  onChooseFile() {
    wx.chooseMessageFile({ count: 1, type: 'file', success: (res) => {
      const f = res.tempFiles[0];
      this.setData({ filePath: f.path, fileName: f.name, resultUrl: '', resultName: '' });
    }});
  },

  onConvert() {
    if (!this.data.filePath || !this.data.targetFormat) return;
    this.setData({ loading: true });
    wx.uploadFile({
      url: app.globalData.serverUrl + "/api/convert",
      filePath: this.data.filePath,
      name: "file",
      formData: { format: this.data.targetFormat },
      success: (res) => {
        try {
          const data = JSON.parse(res.data);
          if (data.path) {
            const ext = this.data.targetFormat;
            const name = (this.data.fileName || 'file').replace(/\.[^.]+$/, '') + '.' + ext;
            this.setData({ resultUrl: app.globalData.serverUrl + data.path, resultName: name });
          } else {
            wx.showToast({ title: data.error || data.detail || "转换失败", icon: "none" });
          }
        } catch(e) {
          wx.showToast({ title: "服务器异常", icon: "none" });
        }
      },
      fail: () => { wx.showToast({ title: "上传失败", icon: "none" }); },
      complete: () => { this.setData({ loading: false }); }
    });
  },

  onDownload() {
    if (!this.data.resultUrl) return;
    wx.showLoading({ title: "下载中..." });
    wx.downloadFile({
      url: this.data.resultUrl,
      success: (res) => {
        wx.openDocument({
          filePath: res.tempFilePath,
          success: () => { wx.hideLoading(); },
          fail: () => { wx.showToast({ title: "打开失败", icon: "none" }); }
        });
      },
      fail: () => { wx.showToast({ title: "下载失败", icon: "none" }); },
      complete: () => { wx.hideLoading(); }
    });
  }
});
