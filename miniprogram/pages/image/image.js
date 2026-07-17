const app = getApp();
const api = require("../../utils/api");

Page({
  data: { image: "", resultImage: "", brushMode: false, brushReady: false, processing: false, brushSize: 8 },
  brushPts: [],
  canvasCtx: null,
  canvasRect: null,

  onChooseImage() {
    wx.chooseImage({
      count: 1,
      success: (res) => {
        this.setData({ image: res.tempFilePaths[0], resultImage: "", brushMode: false, brushReady: false });
        this.brushPts = [];
        this.canvasCtx = null;
        this.canvasRect = null;
      }
    });
  },

  async onAutoInpaint() {
    if (!this.data.image || this.data.processing) return;
    this.setData({ processing: true });
    try {
      wx.showLoading({ title: "\u5904\u7406\u4e2d..." });
      const result = await api.uploadAndInpaint(this.data.image, { useAuto: true, radius: "5" });
      wx.hideLoading();
      this.setData({ resultImage: result.path });
      wx.showToast({ title: "\u5904\u7406\u5b8c\u6210", icon: "success" });
    } catch(e) {
      wx.hideLoading();
      wx.showToast({ title: e.message || "\u5904\u7406\u5931\u8d25", icon: "none" });
    }
    this.setData({ processing: false });
  },
  
  onToggleBrush() {
    const newMode = !this.data.brushMode;
    this.setData({ brushMode: newMode, brushReady: false });
    this.brushPts = [];
    this.canvasCtx = null;
    this.canvasRect = null;
    if (newMode) {
      const that = this;
      setTimeout(() => {
        that.canvasCtx = wx.createCanvasContext("brushCanvas", that);
        that.canvasCtx.setStrokeStyle("rgba(231,76,60,0.6)");
        that.canvasCtx.setLineWidth(that.data.brushSize);
        that.canvasCtx.setLineCap("round");
        that.canvasCtx.setLineJoin("round");
        // 同步缓存canvas位置（关键修复）
        wx.createSelectorQuery().in(that).select(".brush-overlay").boundingClientRect((rect) => {
          that.canvasRect = rect || { left: 0, top: 0 };
          console.log("Canvas rect cached:", that.canvasRect);
        }).exec();
        that.setData({ brushReady: true });
      }, 300);
    }
  },

  onBrushSizeChange(e) {
    const sz = e.detail.value;
    this.setData({ brushSize: sz });
    if (this.canvasCtx) this.canvasCtx.setLineWidth(sz);
  },
  
  onBrushStart(e) {
    if (!this.canvasCtx || !this.canvasRect) return;
    const t = e.touches[0];
    const x = t.x - this.canvasRect.left;
    const y = t.y - this.canvasRect.top;
    this.brushPts = [{ x, y }];
  },
  
  onBrushMove(e) {
    if (!this.canvasCtx || !this.canvasRect || this.brushPts.length === 0) return;
    const t = e.touches[0];
    const x = t.x - this.canvasRect.left;
    const y = t.y - this.canvasRect.top;
    const prev = this.brushPts[this.brushPts.length - 1];
    this.brushPts.push({ x, y });
    
    this.canvasCtx.beginPath();
    this.canvasCtx.moveTo(prev.x, prev.y);
    this.canvasCtx.lineTo(x, y);
    this.canvasCtx.stroke();
    this.canvasCtx.draw(true);
    
    if (this.brushPts.length >= 2) {
      this.setData({ brushReady: true });
    }
  },
  
  onBrushEnd() {},
  
  async onBrushInpaint() {
    if (!this.data.image || !this.brushPts || this.brushPts.length < 2) {
      wx.showToast({ title: "\u8bf7\u5148\u5728\u56fe\u7247\u4e0a\u6d82\u62b9\u6c34\u5370\u533a\u57df", icon: "none" });
      return;
    }
    if (this.data.processing) return;
    this.setData({ processing: true });
    try {
      wx.showLoading({ title: "\u5904\u7406\u4e2d..." });
      const result = await api.uploadAndInpaint(this.data.image, {
        pointsJson: JSON.stringify(this.brushPts),
        brushRadius: String(this.data.brushSize)
      });
      wx.hideLoading();
      this.setData({ resultImage: result.path, brushMode: false });
      wx.showToast({ title: "\u5904\u7406\u5b8c\u6210", icon: "success" });
    } catch(e) {
      wx.hideLoading();
      wx.showToast({ title: e.message || "\u5904\u7406\u5931\u8d25", icon: "none" });
    }
    this.setData({ processing: false });
  },
  
  onSaveImage() {
    if (!this.data.resultImage) return;
    api.downloadAndSave(this.data.resultImage).catch((e) => {
      wx.showToast({ title: e.message || "\u4fdd\u5b58\u5931\u8d25", icon: "none" });
    });
  },
  
  onReset() {
    this.setData({ image: "", resultImage: "", brushMode: false, brushReady: false, processing: false });
    this.brushPts = [];
    this.canvasCtx = null;
    this.canvasRect = null;
  }
});
