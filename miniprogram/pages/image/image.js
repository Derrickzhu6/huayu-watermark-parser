const app = getApp();
const api = require("../../utils/api");

Page({
  data: { image: "", resultImage: "", brushMode: false, brushReady: false, processing: false, brushSize: 8, imgWidth: 0, imgHeight: 0 },
  brushPts: [],
  canvasCtx: null,
  canvasRect: null,

  onChooseImage() {
    wx.chooseImage({
      count: 1,
      success: (res) => {
        this.setData({ image: res.tempFilePaths[0], resultImage: "", brushMode: false, brushReady: false, imgWidth: 0, imgHeight: 0 });
        this.brushPts = [];
        this.canvasCtx = null;
        this.canvasRect = null;
      }
    });
  },

  // 图片加载完成后记录显示尺寸
  onImageLoaded(e) {
    const { width, height } = e.detail;
    this.setData({ imgWidth: width, imgHeight: height });
    // 动态设置canvas尺寸
    this._setCanvasSize(width, height);
  },

  // 设置canvas画布实际尺寸匹配图片显示尺寸
  _setCanvasSize(w, h) {
    const query = wx.createSelectorQuery().in(this);
    query.select(".brush-overlay").fields({ node: true, size: true }).exec((res) => {
      // 新canvas 2D接口（基础库2.9.0+）
      if (res && res[0] && res[0].node) {
        const canvas = res[0].node;
        canvas.width = w;
        canvas.height = h;
      }
      // 传统canvas：通过样式控制
    });
  },

  async onAutoInpaint() {
    if (!this.data.image || this.data.processing) return;
    this.setData({ processing: true });
    try {
      wx.showLoading({ title: "处理中..." });
      const result = await api.uploadAndInpaint(this.data.image, { useAuto: true, radius: "5" });
      wx.hideLoading();
      this.setData({ resultImage: result.path });
      wx.showToast({ title: "处理完成", icon: "success" });
    } catch(e) {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
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
        // 缓存canvas位置
        wx.createSelectorQuery().in(that).select(".brush-overlay").boundingClientRect((rect) => {
          that.canvasRect = rect || { left: 0, top: 0, width: that.data.imgWidth, height: that.data.imgHeight };
          console.log("Canvas rect:", that.canvasRect);
        }).exec();
        that.setData({ brushReady: true });
      }, 500);
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
      wx.showToast({ title: "请先在图片上涂抹水印区域", icon: "none" });
      return;
    }
    if (this.data.processing) return;
    this.setData({ processing: true });
    try {
      wx.showLoading({ title: "处理中..." });
      const result = await api.uploadAndInpaint(this.data.image, {
        pointsJson: JSON.stringify(this.brushPts),
        brushRadius: String(this.data.brushSize)
      });
      wx.hideLoading();
      this.setData({ resultImage: result.path, brushMode: false });
      wx.showToast({ title: "处理完成", icon: "success" });
    } catch(e) {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }
    this.setData({ processing: false });
  },
  
  onSaveImage() {
    if (!this.data.resultImage) return;
    api.downloadAndSave(this.data.resultImage).catch((e) => {
      wx.showToast({ title: e.message || "保存失败", icon: "none" });
    });
  },
  
  onReset() {
    this.setData({ image: "", resultImage: "", brushMode: false, brushReady: false, processing: false });
    this.brushPts = [];
    this.canvasCtx = null;
    this.canvasRect = null;
  }
});
