const app = getApp();
Page({
  data: { image: "", resultImage: "", brushMode: false, brushPoints: [], autoLoading: false },
  
  onChooseImage() {
    wx.chooseImage({
      count: 1,
      success: (res) => {
        this.setData({ image: res.tempFilePaths[0], resultImage: "" });
      }
    });
  },
  
  onAutoInpaint() {
    if (!this.data.image) return;
    this.setData({ autoLoading: true });
    wx.uploadFile({
      url: app.globalData.serverUrl + "/api/inpaint",
      filePath: this.data.image,
      name: "file",
      formData: { use_auto: "true", radius: "5" },
      success: (res) => {
        try {
          const data = JSON.parse(res.data);
          if (data.success && data.path) {
            this.setData({ resultImage: app.globalData.serverUrl + data.path });
          } else {
            wx.showToast({ title: data.error || "处理失败", icon: "none" });
          }
        } catch(e) {
          wx.showToast({ title: "服务器返回异常", icon: "none" });
        }
      },
      fail: () => { wx.showToast({ title: "上传失败", icon: "none" }); },
      complete: () => { this.setData({ autoLoading: false }); }
    });
  },
  
  onToggleBrush() {
    const newMode = !this.data.brushMode;
    this.setData({ brushMode: newMode });
    if (newMode) {
      setTimeout(() => {
        const query = wx.createSelectorQuery();
        query.select('.brush-canvas').fields({ node: true, size: true }).exec((res) => {
          if (res[0]) {
            const canvas = res[0].node;
            const ctx = canvas.getContext('2d');
            canvas.width = res[0].width;
            canvas.height = res[0].height;
            this.canvas = canvas;
            this.ctx = ctx;
          }
        });
      }, 200);
    }
  },
  
  onBrushStart(e) {
    if (!this.ctx) return;
    const touch = e.touches[0];
    this.brushPts = this.brushPts || [];
    this.brushPts.push({ x: touch.x, y: touch.y });
  },
  
  onBrushMove(e) {
    if (!this.ctx) return;
    const touch = e.touches[0];
    this.brushPts.push({ x: touch.x, y: touch.y });
    const pts = this.brushPts;
    if (pts.length < 2) return;
    const last = pts[pts.length - 1];
    const prev = pts[pts.length - 2];
    this.ctx.beginPath();
    this.ctx.moveTo(prev.x, prev.y);
    this.ctx.lineTo(last.x, last.y);
    this.ctx.strokeStyle = '#e74c3c';
    this.ctx.lineWidth = 10;
    this.ctx.lineCap = 'round';
    this.ctx.stroke();
    this.setData({ brushPoints: this.brushPts });
  },
  
  onBrushEnd() { /* 完成画笔 */ },
  
  onBrushInpaint() {
    if (!this.data.image || !this.brushPts || this.brushPts.length < 2) {
      wx.showToast({ title: "请先涂抹水印区域", icon: "none" });
      return;
    }
    wx.showLoading({ title: "处理中..." });
    wx.uploadFile({
      url: app.globalData.serverUrl + "/api/inpaint",
      filePath: this.data.image,
      name: "file",
      formData: { points_json: JSON.stringify(this.brushPts), brush_radius: "5" },
      success: (res) => {
        try {
          const data = JSON.parse(res.data);
          if (data.success && data.path) {
            this.setData({ resultImage: app.globalData.serverUrl + data.path, brushMode: false });
          } else {
            wx.showToast({ title: data.error || "处理失败", icon: "none" });
          }
        } catch(e) {
          wx.showToast({ title: "处理失败", icon: "none" });
        }
      },
      fail: () => { wx.showToast({ title: "上传失败", icon: "none" }); },
      complete: () => { wx.hideLoading(); }
    });
  },
  
  onSaveImage() {
    if (!this.data.resultImage) return;
    wx.showLoading({ title: "保存中..." });
    wx.downloadFile({
      url: this.data.resultImage,
      success: (res) => {
        wx.saveImageToPhotosAlbum({
          filePath: res.tempFilePath,
          success: () => { wx.showToast({ title: "已保存到相册" }); },
          fail: () => { wx.showToast({ title: "保存失败，请授权", icon: "none" }); }
        });
      },
      fail: () => { wx.showToast({ title: "下载失败", icon: "none" }); },
      complete: () => { wx.hideLoading(); }
    });
  },
  
  onReset() {
    this.setData({ image: "", resultImage: "", brushMode: false, brushPoints: [] });
    this.brushPts = [];
  }
});
