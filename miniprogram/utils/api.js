/** 获取服务器地址 */
function getServerUrl() {
  try {
    var app = getApp();
    return app.globalData.serverUrl || "https://huayu-parser-283531-10-1455208732.sh.run.tcloudbase.com";
  } catch(e) {
    return "https://huayu-parser-283531-10-1455208732.sh.run.tcloudbase.com";
  }
}

/** 先上传文件再调去水印 */
function uploadAndInpaint(filePath, options) {
  options = options || {};
  return new Promise(function(resolve, reject) {
    wx.uploadFile({
      url: getServerUrl() + "/api/upload",
      filePath: filePath,
      name: "file",
      success: function(res) {
        try {
          var uploadData = JSON.parse(res.data);
          if (uploadData.filename) {
            var formData = { filename: uploadData.filename };
            if (options.useAuto) formData.use_auto = "true";
            if (options.brushRadius) formData.brush_radius = options.brushRadius;
            if (options.radius) formData.radius = options.radius;
            if (options.pointsJson) formData.points_json = options.pointsJson;
            
            wx.request({
              url: getServerUrl() + "/api/inpaint",
              method: "POST",
              header: { "Content-Type": "application/x-www-form-urlencoded" },
              data: formData,
              timeout: 60000,
              success: function(r2) {
                // 成功响应: {filename: "...", path: "..."}
                // 失败响应: {detail: "..."} 或 {error: "..."}
                if (r2.data.path) {
                  r2.data.path = getServerUrl() + r2.data.path;
                  resolve(r2.data);
                } else {
                  reject(new Error(r2.data.detail || r2.data.error || "处理失败"));
                }
              },
              fail: function() { reject(new Error("处理请求失败，请检查网络")); }
            });
          } else {
            reject(new Error(uploadData.detail || uploadData.error || "上传失败"));
          }
        } catch(e) {
          reject(new Error("服务器响应异常"));
        }
      },
      fail: function(err) {
        reject(new Error((err && err.errMsg) || "上传失败"));
      }
    });
  });
}

function parseVideo(url) {
  return new Promise(function(resolve, reject) {
    wx.request({
      url: getServerUrl() + "/api/video/parse",
      method: "POST",
      header: { "Content-Type": "application/x-www-form-urlencoded" },
      data: "url=" + encodeURIComponent(url),
      timeout: 30000,
      success: function(res) {
        if (res.data.success) resolve(res.data);
        else reject(new Error(res.data.error || "解析失败"));
      },
      fail: reject
    });
  });
}

function convertFile(filePath, format) {
  return new Promise(function(resolve, reject) {
    wx.uploadFile({
      url: getServerUrl() + "/api/convert",
      filePath: filePath,
      name: "file",
      formData: { format: format },
      success: function(res) {
        try {
          var data = JSON.parse(res.data);
          if (data.path) resolve(data);
          else reject(new Error(data.error || "转换失败"));
        } catch(e) {
          reject(new Error("服务器异常"));
        }
      },
      fail: reject
    });
  });
}

function downloadAndSave(url) {
  return new Promise(function(resolve, reject) {
    wx.showLoading({ title: "下载中..." });
    wx.downloadFile({
      url: url,
      success: function(res) {
        wx.saveImageToPhotosAlbum({
          filePath: res.tempFilePath,
          success: function() { wx.showToast({ title: "已保存到相册" }); resolve(); },
          fail: function() { reject(new Error("保存失败，请授权相册权限")); }
        });
      },
      fail: reject,
      complete: function() { wx.hideLoading(); }
    });
  });
}


function downloadVideo(videoUrl) {
  const app = getApp();
  return new Promise(function(resolve, reject) {
    wx.request({
      url: app.globalData.serverUrl + "/api/video/download",
      method: "POST",
      header: { "Content-Type": "application/x-www-form-urlencoded" },
      data: "url=" + encodeURIComponent(videoUrl),
      timeout: 60000,
      success: function(res) {
        if (res.data.path) {
          var dlUrl = app.globalData.serverUrl + res.data.path;
          wx.downloadFile({
            url: dlUrl,
            success: function(dlRes) {
              wx.saveVideoToPhotosAlbum({
                filePath: dlRes.tempFilePath,
                success: function() { wx.showToast({ title: "已保存到相册" }); resolve(); },
                fail: function() { reject(new Error("保存失败，请授权相册权限")); }
              });
            },
            fail: function() { reject(new Error("下载失败")); }
          });
        } else {
          reject(new Error(res.data.error || "下载失败"));
        }
      },
      fail: function() { reject(new Error("网络错误")); }
    });
  });
}

module.exports = { parseVideo: parseVideo, uploadAndInpaint: uploadAndInpaint, convertFile: convertFile, downloadAndSave: downloadAndSave, downloadVideo: downloadVideo, getServerUrl: getServerUrl };
