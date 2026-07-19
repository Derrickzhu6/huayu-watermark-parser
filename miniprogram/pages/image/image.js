const app = getApp();
const api = require("../../utils/api");

Page({
  data: { image: "", resultImage: "", brushMode: false, brushReady: false, processing: false, brushSize: 8, imgWidth: 0, imgHeight: 0, origWidth: 0, origHeight: 0, scaleX: 1, scaleY: 1 },
  brushPts: [],
  canvasCtx: null,

  onChooseImage() {
    const that = this;
    wx.chooseImage({
      count: 1,
      success: (res) => {
        const tempPath = res.tempFilePaths[0];
        // 获取原图实际尺寸
        wx.getImageInfo({
          src: tempPath,
          success: (info) => {
            that.setData({ 
              image: tempPath, resultImage: "", brushMode: false, brushReady: false,
              imgWidth: 0, imgHeight: 0, origWidth: info.width, origHeight: info.height
            });
            that.brushPts = [];
            that.canvasCtx = null;
          }
        });
      }
    });
  },

  onImageLoaded(e) {
    const { width, height } = e.detail;
    const origW = this.data.origWidth || width;
    const origH = this.data.origHeight || height;
    this.setData({ 
      imgWidth: width, imgHeight: height,
      scaleX: origW / width,
      scaleY: origH / height
    });
  },

  onAutoInpaint() {
    if (!this.data.image || this.data.processing) return;
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, { useAuto: true, radius: "5" }).then((result) => {
      wx.hideLoading();
      this.setData({ resultImage: result.path });
      wx.showToast({ title: "处理完成", icon: "success" });
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }).finally(() => {
      this.setData({ processing: false });
    });
  },
  
  onToggleBrush() {
    const newMode = !this.data.brushMode;
    this.setData({ brushMode: newMode, brushReady: false });
    this.brushPts = [];
    if (newMode) {
      const that = this;
      setTimeout(() => {
        that.canvasCtx = wx.createCanvasContext("brushCanvas", that);
        that.canvasCtx.setStrokeStyle("rgba(231,76,60,0.6)");
        that.canvasCtx.setLineWidth(that.data.brushSize);
        that.canvasCtx.setLineCap("round");
        that.canvasCtx.setLineJoin("round");
        that.setData({ brushReady: true });
      }, 300);
    }
  },

  onBrushSizeChange(e) {
    const sz = e.detail.value;
    this.setData({ brushSize: sz });
    if (this.canvasCtx) this.canvasCtx.setLineWidth(sz);
  },
  
  getCanvasPos(e) {
    // 计算canvas内的坐标（相对于图片显示区域）
    const query = wx.createSelectorQuery().in(this);
    return new Promise((resolve) => {
      query.select(".brush-overlay").boundingClientRect((rect) => {
        if (!rect) { resolve(null); return; }
        const t = e.touches[0];
        const x = t.x - rect.left;
        const y = t.y - rect.top;
        // 缩放为原图坐标
        const scaleX = this.data.scaleX;
        const scaleY = this.data.scaleY;
        resolve({ x: x * scaleX, y: y * scaleY, rawX: x, rawY: y });
      }).exec();
    });
  },

  async onBrushStart(e) {
    if (!this.canvasCtx) return;
    const pos = await this.getCanvasPos(e);
    if (!pos) return;
    this.brushPts = [{ x: pos.x, y: pos.y }];
  },
  
  async onBrushMove(e) {
    if (!this.canvasCtx || this.brushPts.length === 0) return;
    const pos = await this.getCanvasPos(e);
    if (!pos) return;
    const prev = this.brushPts[this.brushPts.length - 1];
    this.brushPts.push({ x: pos.x, y: pos.y });
    
    // 在canvas上画（用原始坐标显示）
    this.canvasCtx.beginPath();
    this.canvasCtx.moveTo(prev.x / this.data.scaleX, prev.y / this.data.scaleY);
    this.canvasCtx.lineTo(pos.x / this.data.scaleX, pos.y / this.data.scaleY);
    this.canvasCtx.stroke();
    this.canvasCtx.draw(true);
    
    if (this.brushPts.length >= 2) {
      this.setData({ brushReady: true });
    }
  },
  
  onBrushEnd() {},
  
  onBrushInpaint() {
    if (!this.data.image || !this.brushPts || this.brushPts.length < 2) {
      wx.showToast({ title: "请先在图片上涂抹水印区域", icon: "none" });
      return;
    }
    if (this.data.processing) return;
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, {
      pointsJson: JSON.stringify(this.brushPts),
      brushRadius: String(this.data.brushSize)
    }).then((result) => {
      wx.hideLoading();
      this.setData({ resultImage: result.path, brushMode: false });
      wx.showToast({ title: "处理完成", icon: "success" });
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }).finally(() => {
      this.setData({ processing: false });
    });
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
  }
});