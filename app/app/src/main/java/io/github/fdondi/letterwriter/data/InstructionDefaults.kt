package io.github.fdondi.letterwriter.data

import io.github.fdondi.letterwriter.core.Prompts
import java.security.MessageDigest

data class InstructionState(
    val effective: String,
    val custom: String?,
    val default: String,
    val baseline: String?,
    val upstreamUpdated: Boolean,
)

/** The repo's default style/structure/search instructions and how a profile's custom text relates to them. */
class InstructionDefaults(private val prompts: Prompts) {
    /** (normalized default text, sha256[:16]) like `instruction_defaults.get_default_instruction`. */
    fun default(kind: InstructionKind): Pair<String, String> {
        val text = prompts.load(kind.defaultFile).replace("\r\n", "\n").trim()
        val hash = MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }.take(16)
        return text to hash
    }

    /** Effective instructions plus whether the repo default changed since the custom text was saved. */
    fun state(profile: UserProfile, kind: InstructionKind): InstructionState {
        val (defaultText, defaultHash) = default(kind)
        val custom = profile.customInstruction(kind).trim().ifEmpty { null }
        val baselineHash = if (custom != null) profile.instructionBaselineHash(kind) else ""
        val upstreamUpdated = when {
            custom != null && baselineHash.isNotEmpty() -> baselineHash != defaultHash
            custom != null -> custom != defaultText.trim()
            else -> false
        }
        return InstructionState(
            effective = custom ?: defaultText,
            custom = custom,
            default = defaultText,
            baseline = if (custom != null) profile.instructionBaselineText(kind).ifEmpty { null } else null,
            upstreamUpdated = upstreamUpdated,
        )
    }
}
