import onnxruntime, sys
sys.path.insert(0, r"C:\AI_Workspace\01_Projects\视频解析API")
model_path = r"C:\AI_Workspace\01_Projects\视频解析API\processors\models\lama.onnx"

sess = onnxruntime.InferenceSession(model_path)
print("Inputs:")
for inp in sess.get_inputs():
    print(f"  {inp.name}: {inp.type} {inp.shape}")
print("Outputs:")
for out in sess.get_outputs():
    print(f"  {out.name}: {out.type} {out.shape}")
