"""Short Studio labels; identifiers and serialized upstream values stay stable."""
PARAMETERS = {
    'SwapModelSelection': '换脸模型', 'SwapperResSelection': '处理精度',
    'AlphaFaceResSelection': '处理精度', 'SimilarityThresholdSlider': '人脸匹配',
    'FaceRestorerEnableToggle': '画质修复', 'FaceRestorerEnable2Toggle': '第二轮修复',
    'FaceRestorerTypeSelection': '修复模型', 'FaceRestorerType2Selection': '修复模型',
    'FaceRestorerBlendSlider': '修复强度', 'FaceRestorerBlend2Slider': '修复强度',
    'FaceRestorerDetTypeSelection': '对齐方式', 'FaceRestorerAutoEnableToggle': '自动调整',
    'FaceFidelityWeightDecimalSlider': '保留细节',
    'FaceExpressionEnableToggle': '保留表情', 'FaceExpressionEnableBothToggle': '保留表情',
    'FrameEnhancerEnableToggle': '画面增强', 'FrameEnhancerTypeSelection': '增强模型',
    'ProvidersPrioritySelection': '运行方式', 'DetectorModelSelection': '人脸检测',
    'RecognitionModelSelection': '人脸识别', 'LandmarkDetectToggle': '精细定位',
    'DFMModelSelection': 'DFM 模型', 'OccluderEnableToggle': '保留遮挡',
    'DFLXSegEnableToggle': 'XSeg 遮罩', 'FaceParserEnableToggle': '人脸分区',
    'FinalBorderBlendEnableToggle': '柔化边缘', 'FinalBorderBlendAmountSlider': '柔化程度',
    'VirtualCameraToggle': '虚拟摄像头', 'FFQualitySlider': '导出质量',
    'MaxFacesToDetectSlider': '检测人数', 'MaxThreadsSlider': '并行任务数',
}
BUTTONS = {
    'clearTargetFacesButton': '清除目标人脸', 'saveImageButton': '保存当前画面',
    'batchImageButton': '批量处理', 'batchallImageButton': '批量处理所有人脸',
    'openEditorButton': '编辑人脸特征', 'openEmbeddingButton': '导入',
    'saveEmbeddingButton': '保存', 'saveEmbeddingAsButton': '另存为',
    'addJobButton': '加入队列', 'deleteJobButton': '删除任务',
    'buttonProcessSelected': '运行所选任务', 'buttonProcessAll': '运行全部任务',
    'loadJobButton': '载入任务', 'refreshJobListButton': '刷新',
    'buttonTargetVideosPath': '素材文件夹', 'buttonInputFacesPath': '参考脸文件夹',
    'savePresetButton': '保存预设', 'applyPresetButton': '应用预设',
}
SECTIONS = {'Swapper': '换脸', 'Swap strength and likeness': '相似度与强度',
            'Face Restorer': '画质修复', 'Face expressions': '表情', 'Face Editor': '人脸编辑'}


def apply_labels(window):
    for name, text in PARAMETERS.items():
        widget = window.parameter_widgets.get(name)
        if widget is not None and hasattr(widget, 'label_widget'):
            widget.label_widget.setText(text)
    for name, text in BUTTONS.items():
        widget = getattr(window, name, None)
        if widget is not None:
            widget.setText(text)
    for section in window.parameter_sections.values():
        text = section.header_button.text()
        if text in SECTIONS:
            section.header_button.setText(SECTIONS[text])
