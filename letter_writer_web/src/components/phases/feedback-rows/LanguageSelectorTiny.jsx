import React from "react";
import LanguageSelector from "../../LanguageSelector";

export function LanguageSelectorTiny({ fieldId, observation, translation, disabled }) {
  const fieldViewLanguage = translation.getFieldViewLanguage(fieldId);
  const handleFieldLanguageChange = async (code) => {
    translation.setFieldViewLanguage(fieldId, code);
    if (code === "source" || !observation) return;
    await translation.translateField(fieldId, observation, code);
  };
  return (
    <LanguageSelector
      languages={translation.languages}
      viewLanguage={fieldViewLanguage}
      onLanguageChange={handleFieldLanguageChange}
      hasTranslation={(code) => translation.hasTranslation(fieldId, code)}
      disabled={disabled}
      isTranslating={translation.isTranslating[fieldId] || false}
      size="tiny"
    />
  );
}
