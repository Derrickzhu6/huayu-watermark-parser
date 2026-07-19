const app = getApp();
const api = require("../../utils/api");

Page({
  data: { image: "", resultImage: "", brushMode: false, processing: false, brushSize: 8, imgW: 0, imgH: 0, origW: 0, origH: 0, scaleX: 1, scaleY: 1 },
  brushPts: [],
  canvasCtx: null,
  canvasRect: null,
  isDrawing: false,

  onChooseImage() {
    const that = this;
    wx.chooseImage({
      count: 1,
      sizeType: ["original"],
      success: (res) => {
        const path = res.tempFilePaths[0];
        wx.getImageInfo({
          src: path,
          success: (info) => {
            that.setData({ 
              image: path, resultImage: "", brushMode: false, processing: false,
              imgW: 0, imgH: 0, origW: info.width, origH: info.height, scaleX: 1, scaleY: 1
            });
            that.brushPts = [];
            that.canvasCtx = null;
            that.canvasRect = null;
          }
        });
      }
    });
  },

  onImageLoaded(e) {
    const w = e.detail.width, h = e.detail.height;
    const ow = this.data.origW || w, oh = this.data.origH || h;
    this.setData({ imgW: w, imgH: h, scaleX: ow / w, scaleY: oh / h });
    const that = this;
    setTimeout(() => {
      wx.createSelectorQuery().in(that).select(".brush-overlay").boundingClientRect((rect) => {
        if (rect) { that.canvasRect = rect; }
      }).exec();
    }, 200);
  },

  onAutoInpaint() {
    if (!this.data.image || this.data.processing) return;
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, { useAuto: true, radius: "5" }).then((res) => {
      this.setData({ resultImage: res.path });
      wx.hideLoading();
      wx.showToast({ title: "完成", icon: "success" });
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }).finally(() => { this.setData({ processing: false }); });
  },

  onToggleBrush() {
    const m = !this.data.brushMode;
    this.setData({ brushMode: m });
    this.brushPts = [];
    this.isDrawing = false;
    if (m) {
      const that = this;
      setTimeout(() => {
        that.canvasCtx = wx.createCanvasContext("brushCanvas", that);
        that.canvasCtx.setStrokeStyle("rgba(231,76,60,0.6)");
        that.canvasCtx.setLineWidth(that.data.brushSize);
        that.canvasCtx.setLineCap("round");
        that.canvasCtx.setLineJoin("round");
        wx.createSelectorQuery().in(that).select(".brush-overlay").boundingClientRect((rect) => {
          if (rect) { that.canvasRect = rect; console.log("Rect:", JSON.stringify(rect)); }
        }).exec();
      }, 300);
    }
  },

  onBrushSizeChange(e) {
    this.setData({ brushSize: e.detail.value });
    if (this.canvasCtx) this.canvasCtx.setLineWidth(e.detail.value);
  },

  onBrushStart(e) {
    if (!this.canvasCtx || !this.canvasRect) return;
    this.isDrawing = true;
    const t = e.touches[0];
    const rx = (t.x - this.canvasRect.left);
    const ry = (t.y - this.canvasRect.top);
    // 存原始图坐标（缩放后）
    this.brushPts = [{
      x: Math.round(rx * this.data.scaleX),
      y: Math.round(ry * this.data.scaleY)
    }];
  },

  onBrushMove(e) {
    if (!this.isDrawing || !this.canvasCtx || !this.canvasRect || this.brushPts.length === 0) return;
    const t = e.touches[0];
    const rx = (t.x - this.canvasRect.left);
    const ry = (t.y - this.canvasRect.top);
    const prev = this.brushPts[this.brushPts.length - 1];
    const pt = {
      x: Math.round(rx * this.data.scaleX),
      y: Math.round(ry * this.data.scaleY)
    };
    this.brushPts.push(pt);
    // canvas显示用屏幕坐标（不缩放）
    this.canvasCtx.beginPath();
    this.canvasCtx.moveTo(prev.x / this.data.scaleX, prev.y / this.data.scaleY);
    this.canvasCtx.lineTo(pt.x / this.data.scaleX, pt.y / this.data.scaleY);
    this.canvasCtx.stroke();
    this.canvasCtx.draw(true);
  },

  onBrushEnd() { this.isDrawing = false; },

  onBrushInpaint() {
    if (!this.data.image || this.brushPts.length < 2) {
      wx.showToast({ title: "请先在图片上涂抹水印区域", icon: "none" });
      return;
    }
    if (this.data.processing) return;
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, {
      pointsJson: JSON.stringify(this.brushPts),
      brushRadius: String(this.data.brushSize)
    }).then((res) => {
      this.setData({ resultImage: res.path, brushMode: false });
      wx.hideLoading();
      wx.showToast({ title: "完成", icon: "success" });
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }).finally(() => { this.setData({ processing: false }); });
  },

  onSaveImage() {
    if (!this.data.resultImage) return;
    api.downloadAndSave(this.data.resultImage).catch((e) => {
      wx.showToast({ title: e.message || "保存失败", icon: "none" });
    });
  },

  onReset() {
    this.setData({ image: "", resultImage: "", brushMode: false, processing: false });
    this.brushPts = []; this.canvasCtx = null; this.canvasRect = null; this.isDrawing = false;
  }
});