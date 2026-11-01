// Display labels and grouping. Parameter keys and stored values stay upstream-compatible.

export const TABS: { id: string; label: string; sections: string[] }[] = [
  { id: "swap", label: "换脸", sections: ["swapper:Swapper", "swapper:Swap strength and likeness", "swapper:Face Re-Aging"] },
  { id: "mask", label: "遮罩", sections: ["swapper:Masks", "swapper:Original Face Parsers"] },
  {
    id: "quality",
    label: "画质",
    sections: ["common:Face Restorer", "swapper:Textures and colors", "swapper:Blend Adjustments", "denoiser:ReF-LDM Denoiser", "settings:Frame Enhancer"],
  },
  { id: "motion", label: "表情与姿态", sections: ["common:Face expressions", "face_editor:", "swapper:Face Landmarks Correction"] },
  { id: "detect", label: "检测与跟踪", sections: ["settings:Detectors", "settings:Face Tracking", "settings:Swap settings"] },
];

export const SECTION_TITLES: Record<string, string> = {
  "swapper:Swapper": "换脸模型",
  "swapper:Swap strength and likeness": "强度与相似度",
  "swapper:Face Re-Aging": "年龄调整",
  "swapper:Masks": "遮罩",
  "swapper:Original Face Parsers": "保留原脸区域",
  "common:Face Restorer": "人脸修复",
  "swapper:Textures and colors": "纹理与色彩",
  "swapper:Blend Adjustments": "融合",
  "denoiser:ReF-LDM Denoiser": "ReF-LDM 去噪",
  "settings:Frame Enhancer": "画面增强",
  "common:Face expressions": "表情还原",
  "face_editor:": "人脸编辑",
  "swapper:Face Landmarks Correction": "关键点校正",
  "settings:Detectors": "人脸检测",
  "settings:Face Tracking": "人脸跟踪",
  "settings:Swap settings": "匹配与 VR",
  "settings:General": "运行",
  "settings:Output Settings": "输出位置",
  "settings:Video Recording Settings": "视频编码",
  "settings:Misc": "其他",
  "settings:Webcam and Virtualcam Settings": "摄像头与虚拟摄像头",
};

// Settings sheet sections (global options that are not per-face adjustments).
export const SETTINGS_SECTIONS = ["settings:General", "settings:Video Recording Settings", "settings:Output Settings", "settings:Misc"];

export const LABELS: Record<string, string> = {
  SwapModelSelection: "换脸模型",
  SwapperResSelection: "处理精度",
  AlphaFaceResSelection: "处理精度",
  SimilarityThresholdSlider: "匹配阈值",
  PreSwapSharpnessDecimalSlider: "换脸前锐化",
  FaceAlignmentInterpolation: "对齐插值",
  SecondarySwapperEnableToggle: "第二换脸模型",
  DFMModelSelection: "DFM 模型",
  StrengthEnableToggle: "增强强度",
  StrengthAmountSlider: "强度",
  FaceLikenessEnableToggle: "相似度调整",
  FaceKeypointsReplaceEnableToggle: "关键点替换",
  FaceRestorerEnableToggle: "人脸修复",
  FaceRestorerTypeSelection: "修复模型",
  FaceRestorerBlendSlider: "修复强度",
  FaceRestorerDetTypeSelection: "对齐方式",
  FaceFidelityWeightDecimalSlider: "保留细节",
  FaceRestorerEnable2Toggle: "第二轮修复",
  FaceRestorerType2Selection: "修复模型",
  FaceRestorerBlend2Slider: "修复强度",
  BordermaskEnableToggle: "边框遮罩",
  OccluderEnableToggle: "保留遮挡物",
  DFLXSegEnableToggle: "XSeg 遮罩",
  ClipEnableToggle: "文字遮罩",
  FaceParserEnableToggle: "人脸分区",
  FinalBlendAdjEnableToggle: "整体融合",
  FinalBorderBlendEnableToggle: "柔化边缘",
  FinalBorderBlendAmountSlider: "柔化程度",
  OverallMaskBlendAmountSlider: "遮罩羽化",
  ColorNoiseDecimalSlider: "颗粒噪点",
  FaceReagingEnableToggle: "年龄调整",
  FaceReagingSourceAgeSlider: "原年龄",
  FaceReagingTargetAgeSlider: "目标年龄",
  FaceExpressionEnableBothToggle: "还原表情",
  FaceEditorEnableToggle: "人脸编辑",
  FrameEnhancerEnableToggle: "画面增强",
  FrameEnhancerTypeSelection: "增强模型",
  FrameEnhancerBlendSlider: "增强强度",
  ProvidersPrioritySelection: "运行方式",
  nThreadsSlider: "并行线程",
  DetectorModelSelection: "检测模型",
  RecognitionModelSelection: "识别模型",
  DetectorScoreSlider: "检测阈值",
  MaxFacesToDetectSlider: "最多检测人数",
  LandmarkDetectToggle: "精细定位",
  FaceTrackingEnableToggle: "人脸跟踪",
  AutoRotationToggle: "自动旋转",
  ManualRotationEnableToggle: "手动旋转",
  SwapOnlyBestMatchEnableToggle: "只替换最佳匹配",
  EmbMergeMethodSelection: "多参考脸合并",
  VR180ModeEnableToggle: "VR180 模式",
  FFQualitySlider: "视频质量",
  HDREncodeToggle: "HDR 编码",
  ImageFormatToggle: "图片导出为 JPEG",
  KeepModelsAliveToggle: "保持模型常驻",
  OutputToTargetLocationToggle: "保存到素材所在位置",
  OutputFpsCapEnableToggle: "限制输出帧率",
  WebcamMaxNoSelection: "摄像头数量",
  WebcamBackendSelection: "摄像头接口",
  WebcamMaxResSelection: "摄像头分辨率",
  WebCamMaxFPSSelection: "摄像头帧率",
  SendVirtCamFramesEnableToggle: "输出到虚拟摄像头",
  VirtCamBackendSelection: "虚拟摄像头类型",
  OutputMaxFpsSlider: "最高帧率",
  GlobalInputResizeToggle: "处理前统一缩放",
  GlobalInputResizeSizeSelection: "缩放到",
  PreserveOutputDirectoryStructureToggle: "保留素材的文件夹结构",
  ClusterOutputBySourceToggle: "按参考脸分文件夹",
  FrameEnhancerDownToggle: "增强后缩小到 1080p",
};

// Behaviour of the previous Qt window (theme, toasts, playback buffering, folder
// scanning, autosave). The new interface implements these concerns itself.
export const UI_ONLY = new Set([
  "ThemeSelection", "KeepControlsToggle", "TrackMarkersToggle", "TheatreModeUsesFullscreenToggle",
  "VideoPlaybackCustomFpsToggle", "VideoPlaybackCustomFpsSlider", "VideoPlaybackBufferingToggle",
  "VideoPlaybackSegmentsToggle", "VideoPlaybackLoopToggle", "FrameSkipStepSlider", "LiveSoundVolumeDecimalSlider",
  "ConfirmBeforeStoppingRecordingToggle", "OpenOutputToggle", "TargetMediaFolderRecursiveToggle",
  "InputFacesFolderRecursiveToggle", "AutoSaveWorkspaceToggle", "AutoSaveLastWorkspaceToggle", "AutoLoadWorkspaceToggle",
  "SliderMouseWheelControlToggle", "SortEmbeddingsAZToggle", "SkipClearConfirmationToggle", "EnableMediaToastToggle",
  "ToastDurationText", "ShowSeekBarThumbnailsToggle", "VideoSeekMaxFrameSlider", "AutoSwapToggle", "KeepInputToggle",
]);

// Tuning of Fusion's playback worker pool; the new exporter uses its own pool (线程数).
export const NOT_YET = new Set(["nStreamSlider", "FrameWorkerDelayDecimalSlider"]);

export function fieldLabel(key: string, fallback: string) {
  return LABELS[key] ?? fallback;
}

export function sectionTitle(id: string, fallback: string) {
  return SECTION_TITLES[id] ?? (fallback || id);
}

export function formatBytes(n: number) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n >= 1e6) return `${Math.round(n / 1e6)} MB`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} KB`;
  return `${n} B`;
}

export function formatTime(seconds: number) {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
}
