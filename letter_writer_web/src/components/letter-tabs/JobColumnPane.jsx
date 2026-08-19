import React from "react";
import JobDescriptionColumn from "../JobDescriptionColumn";

export default function JobColumnPane({
  jobText,
  companyReport,
  requirements,
  competences,
  scaleConfig,
  overrides,
  width,
  minWidth,
  languages,
  onHeaderClick,
  isExpanded,
  onClose,
  selectedKeyTerm,
  onTermClick,
  competenceCounts,
  finalAssemblyText,
}) {
  return (
    <JobDescriptionColumn
      jobText={jobText}
      companyReport={companyReport}
      requirements={requirements}
      competences={competences}
      scaleConfig={scaleConfig}
      overrides={overrides}
      width={width}
      minWidth={minWidth}
      languages={languages}
      onHeaderClick={onHeaderClick}
      isExpanded={isExpanded}
      onClose={onClose}
      selectedKeyTerm={selectedKeyTerm}
      onTermClick={onTermClick}
      competenceCounts={competenceCounts}
      finalAssemblyText={finalAssemblyText}
    />
  );
}
