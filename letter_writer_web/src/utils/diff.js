import { diffSentences, diffWords } from 'diff';

/**
 * Creates a sentence-focused diff representation of text changes.
 * Detects separate changed sentence regions within a paragraph.
 * 
 * @param {string} original - Original text
 * @param {string} edited - Edited text
 * @returns {Array} Array of diff objects, or empty array if no changes.
 *   Each diff: {type: 'diff'|'full', original: string, edited: string}
 *   If >50% changed overall, returns single full paragraph diff.
 */
export function createTextDiff(original, edited) {
  if (!original || !edited) {
    // If one is empty, treat as full change
    if (original || edited) {
      return [{ type: 'full', original: original || '', edited: edited || '' }];
    }
    return [];
  }

  // If texts are identical, return empty array
  if (original === edited) {
    return [];
  }

  // Use diff library to get word-level changes
  const wordDiff = diffWords(original, edited);
  
  // Convert to word arrays for easier processing
  const originalWords = [];
  const editedWords = [];
  let originalWordCount = 0;
  let editedWordCount = 0;
  let changedWordCount = 0;
  
  for (const part of wordDiff) {
    const words = part.value.trim().split(/\s+/).filter(w => w.length > 0);
    
    if (part.removed) {
      originalWords.push(...words);
      originalWordCount += words.length;
      changedWordCount += words.length;
    } else if (part.added) {
      editedWords.push(...words);
      editedWordCount += words.length;
      changedWordCount += words.length;
    } else {
      // Unchanged text
      originalWords.push(...words);
      editedWords.push(...words);
      originalWordCount += words.length;
      editedWordCount += words.length;
    }
  }

  // Calculate change percentage
  const totalWords = Math.max(originalWordCount, editedWordCount);
  const changePercentage = totalWords > 0 ? (changedWordCount / totalWords) * 100 : 0;

  // If more than 50% changed, return full paragraph as single diff
  if (changePercentage > 50) {
    return [{ type: 'full', original, edited }];
  }

  // Prefer sentence-level regions so persisted corrections include full changed sentences.
  const sentenceDiff = diffSentences(original, edited);
  const changeRegions = findSentenceChangeRegions(sentenceDiff);
  
  if (changeRegions.length === 0) {
    return [];
  }

  // Convert each region to a diff object
  return changeRegions.map(region => ({
    type: 'diff',
    original: region.originalChanged,
    edited: region.editedChanged,
  }));
}

/**
 * Find separate changed sentence regions from a sentence diff.
 * Adjacent removed+added parts are grouped as one change region.
 * 
 * @param {Array} sentenceDiff - Output from diffSentences()
 * @returns {Array} Array of change region objects, each with:
 *   {originalChanged: string, editedChanged: string}
 */
function findSentenceChangeRegions(sentenceDiff) {
  const regions = [];
  
  let originalChanged = '';
  let editedChanged = '';
  
  const closeRegion = () => {
    const originalTrimmed = originalChanged.trim();
    const editedTrimmed = editedChanged.trim();
    if (originalTrimmed || editedTrimmed) {
      regions.push({
        originalChanged: originalTrimmed,
        editedChanged: editedTrimmed,
      });
    }
    originalChanged = '';
    editedChanged = '';
  };

  for (let i = 0; i < sentenceDiff.length; i++) {
    const part = sentenceDiff[i];
    const value = part.value;
    
    if (part.removed) {
      originalChanged += value;
      
      // Keep region open if next part is another change chunk.
      if (i + 1 < sentenceDiff.length && sentenceDiff[i + 1].added) {
        continue;
      }
      
    } else if (part.added) {
      editedChanged += value;
      
      // Close when next part is unchanged or end of array.
      if (i + 1 >= sentenceDiff.length || (!sentenceDiff[i + 1].removed && !sentenceDiff[i + 1].added)) {
        closeRegion();
      }
      
    } else {
      // Unchanged text closes any open change region.
      if (originalChanged || editedChanged) {
        closeRegion();
      }
    }
  }
  
  // Close remaining region at end.
  if (originalChanged || editedChanged) {
    closeRegion();
  }
  
  return regions;
}
