import { diffWords } from 'diff';

/**
 * Creates a compact diff representation of text changes.
 * Detects multiple separate change regions within a paragraph.
 * 
 * @param {string} original - Original text
 * @param {string} edited - Edited text
 * @returns {Array} Array of diff objects, or empty array if no changes.
 *   Each diff: {type: 'diff'|'full', original: string, edited: string}
 *   If >20% changed overall, returns single full paragraph diff.
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

  // If more than 20% changed, return full paragraph as single diff
  if (changePercentage > 20) {
    return [{ type: 'full', original, edited }];
  }

  // Find all separate change regions from the diff
  const changeRegions = findAllChangeRegions(wordDiff);
  
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
 * Find all separate change regions from a word diff.
 * Uses the diff library's output to identify separate change regions.
 * The diff library returns parts in sequence: unchanged, removed, added, unchanged, etc.
 * Adjacent removed+added parts represent a single replacement change.
 * 
 * @param {Array} wordDiff - Output from diffWords()
 * @returns {Array} Array of change region objects, each with:
 *   {originalChanged: string, editedChanged: string}
 */
function findAllChangeRegions(wordDiff) {
  const regions = [];
  
  let originalChanged = '';
  let editedChanged = '';
  
  for (let i = 0; i < wordDiff.length; i++) {
    const part = wordDiff[i];
    
    if (part.removed) {
      // Removed text - start or continue a change region
      originalChanged += (originalChanged ? ' ' : '') + part.value.trim();
      
      // Check if next part is added (replacement case)
      if (i + 1 < wordDiff.length && wordDiff[i + 1].added) {
        continue; // Will process added part next
      }
      
    } else if (part.added) {
      // Added text - usually part of a replacement (after removed)
      editedChanged += (editedChanged ? ' ' : '') + part.value.trim();
      
      // Check if next part is unchanged or end - close region
      if (i + 1 >= wordDiff.length || (!wordDiff[i + 1].removed && !wordDiff[i + 1].added)) {
        // Close the region
        if (originalChanged || editedChanged) {
          regions.push({
            originalChanged: originalChanged.trim(),
            editedChanged: editedChanged.trim(),
          });
        }
        
        // Reset for next region
        originalChanged = '';
        editedChanged = '';
      }
      
    } else {
      // Unchanged text - if we have an open change region, close it
      if (originalChanged || editedChanged) {
        regions.push({
          originalChanged: originalChanged.trim(),
          editedChanged: editedChanged.trim(),
        });
        
        // Reset
        originalChanged = '';
        editedChanged = '';
      }
    }
  }
  
  // Close any remaining open region at the end
  if (originalChanged || editedChanged) {
    regions.push({
      originalChanged: originalChanged.trim(),
      editedChanged: editedChanged.trim(),
    });
  }
  
  return regions;
}
