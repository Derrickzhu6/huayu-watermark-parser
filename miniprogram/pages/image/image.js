const api = require("../../utils/api");

Page({
  data: { 
    image: "", 
    resultImage: "", 
    brushMode: false, 
    processing: false, 
    brushSize: 8,
    canvasW: 300,
    canvasH: 150
  },
  brushPts: [],
  ctx: null,
  imgRect: null,
  isDrawing: false,
  origW: 0,
  origH: 0,

  onChooseImage() {
    const that = this;
    wx.chooseImage({
      count: 1,
      sizeType: ["original"],
      success: (res) => {
        that.setData({ 
          image: res.tempFilePaths[0], 
          resultImage: "", 
          brushMode: false, 
          processing: false,
          canvasW: 300,
          canvasH: 150
        });
        that.brushPts = [];
        that.ctx = null;
        that.imgRect = null;
        that.isDrawing = false;
        that.origW = 0;
        that.origH = 0;
      }
    });
  },

  onImageLoaded() {
    const that = this;
    wx.getImageInfo({
      src: that.data.image,
      success: (info) => {
        that.origW = info.width;
        that.origH = info.height;
      }
    });
    setTimeout(() => {
      wx.createSelectorQuery().in(that)
        .select(".image-wrap")
        .boundingClientRect((rect) => {
          if (rect && rect.width > 0 && rect.height > 0) {
            const w = Math.round(rect.width);
            const h = Math.round(rect.height);
            that.imgRect = { left: rect.left, top: rect.top, width: w, height: h };
            that.setData({ canvasW: w, canvasH: h }, () => {
              if (!that.ctx) {
                that.ctx = wx.createCanvasContext("brushCanvas", that);
              }
            });
          }
        }).exec();
    }, 400);
  },

  onToggleBrush() {
    const m = !this.data.brushMode;
    this.setData({ brushMode: m });
    this.brushPts = [];
    this.isDrawing = false;
    if (this.ctx) {
      this.ctx.clearRect(0, 0, this.data.canvasW, this.data.canvasH);
      this.ctx.draw();
    }
    // 如果还没拿到尺寸，再查
    if (m && !this.imgRect) {
      wx.createSelectorQuery().in(this)
        .select(".image-wrap")
        .boundingClientRect((rect) => {
          if (rect && rect.width > 0 && rect.height > 0) {
            const w = Math.round(rect.width);
            const h = Math.round(rect.height);
            this.imgRect = { left: rect.left, top: rect.top, width: w, height: h };
            this.setData({ canvasW: w, canvasH: h });
            if (!this.ctx) {
              this.ctx = wx.createCanvasContext("brushCanvas", this);
            }
          }
        }).exec();
    }
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

  onBrushStart(e) {
    if (!this.ctx || !this.imgRect || !this.data.brushMode) return;
    this.isDrawing = true;
    const t = e.touches[0];
    const x = t.x - this.imgRect.left;
    const y = t.y - this.imgRect.top;
    const px = Math.max(0, Math.round(x));
    const py = Math.max(0, Math.round(y));
    this.brushPts = [{ x: px, y: py }];
    this.ctx.setStrokeStyle("#e74c3c");
    this.ctx.setLineWidth(this.data.brushSize);
    this.ctx.setLineCap("round");
    this.ctx.setLineJoin("round");
    this.ctx.beginPath();
    this.ctx.moveTo(px, py);
    this.ctx.lineTo(px + 0.5, py + 0.5);
    this.ctx.stroke();
    this.ctx.draw(true);
  },

  onBrushMove(e) {
    if (!this.isDrawing || !this.ctx || !this.imgRect) return;
    const t = e.touches[0];
    const x = t.x - this.imgRect.left;
    const y = t.y - this.imgRect.top;
    const px = Math.max(0, Math.round(x));
    const py = Math.max(0, Math.round(y));
    const prev = this.brushPts[this.brushPts.length - 1];
    this.brushPts.push({ x: px, y: py });
    this.ctx.beginPath();
    this.ctx.moveTo(prev.x, prev.y);
    this.ctx.lineTo(px, py);
    this.ctx.stroke();
    this.ctx.draw(true);
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
    api.uploadAndInpaint(this.data.image, {
      pointsJson: JSON.stringify(pts),
      brushRadius: String(Math.round(this.data.brushSize * Math.min(sx, sy)))
    }).then((res) => {
      this.setData({ resultImage: res.path, brushMode: false });
    }).catch((e) => {
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
    this.setData({ 
      image: "", resultImage: "", brushMode: false, processing: false,
      canvasW: 300, canvasH: 150
    });
    this.brushPts = [];
    this.ctx = null;
    this.imgRect = null;
    this.isDrawing = false;
    this.origW = 0;
    this.origH = 0;
  }
});
