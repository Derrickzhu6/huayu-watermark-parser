const api = require("../../utils/api");

Page({
  data: { 
    image: "", resultImage: "", brushMode: false, processing: false, brushSize: 8,
    brushDots: [], lastX: 0, lastY: 0, brushPtsLen: 0
  },
  brushPts: [],
  isDrawing: false,
  imgRect: null,
  origW: 0,
  origH: 0,
  rectReady: false,

  onChooseImage() {
    wx.chooseImage({
      count: 1,
      sizeType: ["original"],
      success: (res) => {
        this.setData({ image: res.tempFilePaths[0], resultImage: "", brushMode: false, processing: false, 
          brushDots: [], lastX: 0, lastY: 0, brushPtsLen: 0 });
        this.brushPts = []; this.isDrawing = false; this.imgRect = null;
        this.origW = 0; this.origH = 0; this.rectReady = false;
      }
    });
  },

  onImageLoaded() {
    const that = this;
    wx.getImageInfo({
      src: that.data.image,
      success: (info) => { that.origW = info.width; that.origH = info.height; }
    });
    setTimeout(() => { that._queryRect(); }, 500);
  },

  _queryRect() {
    const that = this;
    wx.createSelectorQuery().in(that)
      .select(".image-wrap")
      .boundingClientRect((rect) => {
        if (rect && rect.width > 0 && rect.height > 0) {
          that.imgRect = {
            left: rect.left,
            top: rect.top,
            width: Math.round(rect.width),
            height: Math.round(rect.height)
          };
          that.rectReady = true;
        }
      }).exec();
  },

  onToggleBrush() {
    const m = !this.data.brushMode;
    this.setData({ brushMode: m, brushDots: [], lastX: 0, lastY: 0, brushPtsLen: 0 });
    this.brushPts = [];
    this.isDrawing = false;
    if (m && !this.rectReady) {
      this._queryRect();
    }
  },

  onBrushSizeChange(e) {
    this.setData({ brushSize: e.detail.value });
  },

  onAutoInpaint() {
    if (!this.data.image || this.data.processing) return;
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, { useAuto: true, radius: "5" }).then((res) => {
      this.setData({ resultImage: res.path, brushDots: [] });
      wx.hideLoading();
      wx.showToast({ title: "完成", icon: "success" });
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }).finally(() => { this.setData({ processing: false }); });
  },

  onBrushStart(e) {
    if (!this.rectReady || !this.data.brushMode) return;
    this.isDrawing = true;
    const t = e.touches[0];
    const cx = t.clientX !== undefined ? t.clientX : t.x;
    const cy = t.clientY !== undefined ? t.clientY : t.y;
    const px = Math.round(cx - this.imgRect.left);
    const py = Math.round(cy - this.imgRect.top);
    if (px < 0 || py < 0 || px > this.imgRect.width || py > this.imgRect.height) {
      this.setData({ lastX: cx, lastY: cy, brushPtsLen: 0 });
      return;
    }
    this.brushPts = [{ x: px, y: py }];
    this.setData({ brushDots: [{ x: px, y: py }], lastX: px, lastY: py, brushPtsLen: 1 });
  },

  onBrushMove(e) {
    if (!this.isDrawing || !this.rectReady) return;
    const t = e.touches[0];
    const cx = t.clientX !== undefined ? t.clientX : t.x;
    const cy = t.clientY !== undefined ? t.clientY : t.y;
    const px = Math.round(cx - this.imgRect.left);
    const py = Math.round(cy - this.imgRect.top);
    if (px < 0 || py < 0 || px > this.imgRect.width || py > this.imgRect.height) {
      this.setData({ lastX: cx, lastY: cy });
      return;
    }
    this.brushPts.push({ x: px, y: py });
    const newDots = this.data.brushDots.concat([{ x: px, y: py }]);
    this.setData({ brushDots: newDots, lastX: px, lastY: py, brushPtsLen: this.brushPts.length });
  },

  onBrushEnd() { this.isDrawing = false; },

  onBrushInpaint() {
    if (!this.data.image || this.brushPts.length < 2) {
      wx.showToast({ title: "请在图片上涂抹水印区域", icon: "none" });
      return;
    }
    if (this.data.processing) return;
    let sx = 1, sy = 1;
    if (this.origW > 0 && this.imgRect && this.imgRect.width > 0) {
      sx = this.origW / this.imgRect.width;
      sy = this.origH / this.imgRect.height;
    }
    const pts = this.brushPts.map(p => ({ x: Math.round(p.x * sx), y: Math.round(p.y * sy) }));
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, {
      pointsJson: JSON.stringify(pts),
      brushRadius: String(Math.round(this.data.brushSize * (sx + sy) / 2))
    }).then((res) => {
      this.setData({ resultImage: res.path, brushMode: false, brushDots: [] });
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
    this.setData({ image: "", resultImage: "", brushMode: false, processing: false, brushDots: [], lastX: 0, lastY: 0, brushPtsLen: 0 });
    this.brushPts = []; this.isDrawing = false; this.imgRect = null; this.rectReady = false;
    this.origW = 0; this.origH = 0;
  }
});
