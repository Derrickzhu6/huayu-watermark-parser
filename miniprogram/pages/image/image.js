const app = getApp();
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
  canvasCtx: null,
  imgRect: null,
  isDrawing: false,
  origImgWidth: 0,
  origImgHeight: 0,
  ctxReady: false,

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
        that.canvasCtx = null;
        that.imgRect = null;
        that.isDrawing = false;
        that.origImgWidth = 0;
        that.origImgHeight = 0;
        that.ctxReady = false;
      }
    });
  },

  onImageLoaded() {
    const that = this;
    // 获取原图尺寸
    wx.getImageInfo({
      src: that.data.image,
      success: (info) => {
        that.origImgWidth = info.width;
        that.origImgHeight = info.height;
      }
    });
    // 获取显示尺寸
    setTimeout(() => {
      wx.createSelectorQuery().in(that)
        .select("#mainImage")
        .boundingClientRect((rect) => {
          if (rect && rect.width > 0 && rect.height > 0) {
            const w = Math.round(rect.width);
            const h = Math.round(rect.height);
            that.imgRect = { left: rect.left, top: rect.top, width: w, height: h };
            that.setData({ canvasW: w, canvasH: h }, () => {
              // canvas 尺寸更新后创建上下文（只创建一次）
              if (!that.ctxReady) {
                that.canvasCtx = wx.createCanvasContext("brushCanvas", that);
                that.ctxReady = true;
              }
            });
          }
        }).exec();
    }, 400);
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
    
    // 清除 canvas 上的旧线条
    if (this.canvasCtx) {
      this.canvasCtx.clearRect(0, 0, this.data.canvasW, this.data.canvasH);
      this.canvasCtx.draw();
    }
    
    // 如果还没获取到图片尺寸，再查一次
    if (m && (!this.imgRect || !this.ctxReady)) {
      setTimeout(() => {
        wx.createSelectorQuery().in(this)
          .select("#mainImage")
          .boundingClientRect((rect) => {
            if (rect && rect.width > 0 && rect.height > 0) {
              const w = Math.round(rect.width);
              const h = Math.round(rect.height);
              this.imgRect = { left: rect.left, top: rect.top, width: w, height: h };
              this.setData({ canvasW: w, canvasH: h });
              if (!this.ctxReady) {
                this.canvasCtx = wx.createCanvasContext("brushCanvas", this);
                this.ctxReady = true;
              }
            }
          }).exec();
      }, 200);
    }
  },

  onBrushSizeChange(e) {
    this.setData({ brushSize: e.detail.value });
  },

  onBrushStart(e) {
    if (!this.ctxReady || !this.imgRect || !this.data.brushMode) return;
    this.isDrawing = true;
    const t = e.touches[0];
    const x = t.x - this.imgRect.left;
    const y = t.y - this.imgRect.top;
    const px = Math.max(0, Math.round(x));
    const py = Math.max(0, Math.round(y));
    this.brushPts = [{ x: px, y: py }];
    
    this.canvasCtx.setStrokeStyle("#e74c3c");
    this.canvasCtx.setLineWidth(this.data.brushSize);
    this.canvasCtx.setLineCap("round");
    this.canvasCtx.setLineJoin("round");
    this.canvasCtx.beginPath();
    this.canvasCtx.arc(px, py, this.data.brushSize / 2, 0, 2 * Math.PI);
    this.canvasCtx.fillStyle = "#e74c3c";
    this.canvasCtx.fill();
    this.canvasCtx.draw(true);
  },

  onBrushMove(e) {
    if (!this.isDrawing || !this.ctxReady || !this.imgRect) return;
    const t = e.touches[0];
    const x = t.x - this.imgRect.left;
    const y = t.y - this.imgRect.top;
    const px = Math.max(0, Math.round(x));
    const py = Math.max(0, Math.round(y));
    const prev = this.brushPts[this.brushPts.length - 1];
    this.brushPts.push({ x: px, y: py });
    
    this.canvasCtx.setStrokeStyle("#e74c3c");
    this.canvasCtx.setLineWidth(this.data.brushSize);
    this.canvasCtx.setLineCap("round");
    this.canvasCtx.setLineJoin("round");
    this.canvasCtx.beginPath();
    this.canvasCtx.moveTo(prev.x, prev.y);
    this.canvasCtx.lineTo(px, py);
    this.canvasCtx.stroke();
    this.canvasCtx.draw(true);
  },

  onBrushEnd() { 
    this.isDrawing = false; 
  },

  onBrushInpaint() {
    if (!this.data.image || this.brushPts.length < 2) {
      wx.showToast({ title: "请先在图片上涂抹水印区域", icon: "none" });
      return;
    }
    if (this.data.processing) return;
    
    let scaleX = 1, scaleY = 1;
    if (this.origImgWidth > 0 && this.imgRect && this.imgRect.width > 0) {
      scaleX = this.origImgWidth / this.imgRect.width;
      scaleY = this.origImgHeight / this.imgRect.height;
    }
    const scaledPts = this.brushPts.map(pt => ({
      x: Math.round(pt.x * scaleX),
      y: Math.round(pt.y * scaleY)
    }));
    
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, {
      pointsJson: JSON.stringify(scaledPts),
      brushRadius: String(Math.round(this.data.brushSize * Math.min(scaleX, scaleY)))
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
    this.setData({ 
      image: "", resultImage: "", brushMode: false, processing: false,
      canvasW: 300, canvasH: 150
    });
    this.brushPts = [];
    this.canvasCtx = null;
    this.imgRect = null;
    this.isDrawing = false;
    this.origImgWidth = 0;
    this.origImgHeight = 0;
    this.ctxReady = false;
  }
});
