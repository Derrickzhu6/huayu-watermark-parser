const api = require("../../utils/api");

Page({
  data: { 
    image: "", resultImage: "", brushMode: false, processing: false, brushSize: 8,
    brushDots: []
  },
  brushPts: [],
  isDrawing: false,
  imgRect: null,
  origW: 0,
  origH: 0,

  onChooseImage() {
    wx.chooseImage({
      count: 1,
      sizeType: ["original"],
      success: (res) => {
        this.setData({ image: res.tempFilePaths[0], resultImage: "", brushMode: false, processing: false, brushDots: [] });
        this.brushPts = []; this.isDrawing = false; this.imgRect = null; this.origW = 0; this.origH = 0;
      }
    });
  },

  onImageLoaded() {
    const that = this;
    wx.getImageInfo({
      src: that.data.image,
      success: (info) => { that.origW = info.width; that.origH = info.height; }
    });
    that._updateRect();
  },

  _updateRect() {
    const that = this;
    setTimeout(() => {
      wx.createSelectorQuery().in(that)
        .select(".image-wrap")
        .boundingClientRect()
        .selectViewport().scrollOffset()
        .exec((res) => {
          const rect = res[0];
          const scroll = res[1];
          if (rect && rect.width > 0 && rect.height > 0) {
            that.imgRect = {
              left: rect.left + (scroll ? scroll.scrollLeft : 0),
              top: rect.top + (scroll ? scroll.scrollTop : 0),
              width: rect.width,
              height: rect.height
            };
          }
        });
    }, 400);
  },

  onToggleBrush() {
    const m = !this.data.brushMode;
    this.setData({ brushMode: m, brushDots: [] });
    this.brushPts = [];
    this.isDrawing = false;
    if (m && !this.imgRect) {
      setTimeout(() => { this._updateRect(); }, 200);
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
      this.setData({ resultImage: res.path });
      wx.hideLoading();
      wx.showToast({ title: "完成", icon: "success" });
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }).finally(() => { this.setData({ processing: false }); });
  },

  onBrushStart(e) {
    if (!this.imgRect || !this.data.brushMode) return;
    this.isDrawing = true;
    const t = e.touches[0];
    const px = Math.round(t.x - this.imgRect.left);
    const py = Math.round(t.y - this.imgRect.top);
    if (px < 0 || py < 0 || px > this.imgRect.width || py > this.imgRect.height) return;
    this.brushPts = [{ x: px, y: py }];
    this.setData({ brushDots: [{ x: px, y: py }] });
  },

  onBrushMove(e) {
    if (!this.isDrawing || !this.imgRect) return;
    const t = e.touches[0];
    const px = Math.round(t.x - this.imgRect.left);
    const py = Math.round(t.y - this.imgRect.top);
    if (px < 0 || py < 0 || px > this.imgRect.width || py > this.imgRect.height) return;
    this.brushPts.push({ x: px, y: py });
    // 每5个点显示一个标记，避免太多
    if (this.brushPts.length % 5 === 0) {
      const dots = this.data.brushDots;
      dots.push({ x: px, y: py });
      this.setData({ brushDots: dots });
    }
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
    this.setData({ image: "", resultImage: "", brushMode: false, processing: false, brushDots: [] });
    this.brushPts = []; this.isDrawing = false; this.imgRect = null; this.origW = 0; this.origH = 0;
  }
});
