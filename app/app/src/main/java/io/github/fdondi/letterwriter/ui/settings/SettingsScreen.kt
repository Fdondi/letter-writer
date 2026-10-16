package io.github.fdondi.letterwriter.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.core.ApiKeys
import io.github.fdondi.letterwriter.core.DecisionModelSettings
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.data.LanguageEntry
import io.github.fdondi.letterwriter.data.UserProfile
import io.github.fdondi.letterwriter.decision.DecisionKeys
import io.github.fdondi.letterwriter.llm.ModelOverrides
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.pipeline.FeedbackItems
import io.github.fdondi.letterwriter.pipeline.FeedbackUi
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.write.vendorLabel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.util.Locale

/** Roles the phone's vendor flow uses (autocomplete and agentic stay desktop-only). */
private val PHONE_ROLES = listOf(
    "extraction" to "Reading the job offer",
    "rag_ranker" to "Ranking similar letters",
    "letter_plan" to "Plan",
    "letter_draft" to "Draft",
    "feedback" to "Feedback checks",
    "feedback_review" to "Feedback review",
    "feedback_context" to "Finding context",
    "letter_refine" to "Rewrite",
)

private val KEY_LABELS = mapOf(
    ApiKeys.OPENAI to "OpenAI (also embeddings and web search)",
    ApiKeys.ANTHROPIC to "Anthropic",
    ApiKeys.GEMINI to "Gemini (also LLM translation)",
    ApiKeys.MISTRAL to "Mistral",
    ApiKeys.XAI to "Grok (xAI)",
    ApiKeys.DEEPSEEK to "DeepSeek",
    ApiKeys.GOOGLE_TRANSLATE to "Google Translate",
    ApiKeys.DECISION_MODEL to "Decision model (Jev)",
)

private class Op {
    var busy by mutableStateOf(false)
    var status by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)
}

private suspend fun Op.run(done: String, block: suspend () -> Unit) {
    busy = true
    status = null
    error = null
    try {
        block()
        status = done
    } catch (e: Exception) {
        error = VendorFlowEngine.describe(e)
    } finally {
        busy = false
    }
}

@Composable
private fun OpFeedback(op: Op) {
    if (op.busy) BusyRow("Working")
    op.status?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    ErrorText(op.error)
}

@Composable
fun SettingsScreen(graph: AppGraph, modifier: Modifier = Modifier) {
    val profile by graph.profiles.profile.collectAsState()
    val p = profile ?: return
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ApiKeysSection(graph)
        VendorsSection(graph, p)
        RoleModelsSection(graph, p)
        LanguagesSection(graph, p)
        DecisionModelSection(graph)
    }
}

@Composable
private fun ApiKeysSection(graph: AppGraph) {
    val keys by graph.apiKeys.collectAsState()
    val scope = rememberCoroutineScope()
    val op = remember { Op() }
    var editing by remember { mutableStateOf<String?>(null) }
    var value by remember { mutableStateOf("") }
    SectionCard("API keys") {
        Text("Stored in your account (personal_data/…/secrets/api_keys), shared with the desktop. Values are never shown.", style = MaterialTheme.typography.bodySmall)
        for (field in ApiKeys.ALL) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(KEY_LABELS[field] ?: field, fontWeight = FontWeight.Medium)
                    Text(if (keys.has(field)) "Saved" else "Not saved", style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = {
                    editing = field
                    value = ""
                }) { Text(if (keys.has(field)) "Replace" else "Add") }
            }
            if (editing == field) {
                OutlinedTextField(
                    value = value,
                    onValueChange = { value = it },
                    label = { Text("New key") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(enabled = value.isNotBlank() && !op.busy, onClick = {
                        scope.launch {
                            op.run("Key saved.") {
                                val sub = graph.auth.requireUser().sub
                                graph.profiles.saveApiKey(sub, field, value)
                                graph.apiKeys.value = graph.profiles.loadApiKeys(sub)
                                editing = null
                                value = ""
                            }
                        }
                    }) { Text("Save") }
                    TextButton(onClick = { editing = null }) { Text("Cancel") }
                }
            }
        }
        OpFeedback(op)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun VendorsSection(graph: AppGraph, p: UserProfile) {
    val scope = rememberCoroutineScope()
    val op = remember { Op() }
    val sub = p.sub
    SectionCard("Vendors") {
        Text("Selected by default for a new letter", style = MaterialTheme.typography.titleSmall)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (v in ModelVendor.entries) {
                val on = v.key in p.defaultVendors
                FilterChip(selected = on, enabled = !op.busy, onClick = {
                    val next = if (on) p.defaultVendors - v.key else p.defaultVendors + v.key
                    scope.launch { op.run("Saved.") { graph.profiles.saveDefaultVendors(sub, next); graph.profiles.load(sub) } }
                }, label = { Text(v.label) })
            }
        }
        Text("Reads the job offer and ranks similar letters", style = MaterialTheme.typography.titleSmall)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (v in ModelVendor.entries) {
                FilterChip(selected = p.extractionVendor == v.key, enabled = !op.busy, onClick = {
                    scope.launch { op.run("Saved.") { graph.profiles.saveExtractionVendor(sub, v.key); graph.profiles.load(sub) } }
                }, label = { Text(v.label) })
            }
        }
        Text("Company research models (need web search)", style = MaterialTheme.typography.titleSmall)
        val searchable = graph.catalogs.allModels(searchOnly = true)
        val (current, dropped) = p.backgroundModels(graph.catalogs)
        if (dropped.isNotEmpty()) ErrorText("Saved research models the phone can't run (skipped): ${dropped.joinToString(", ")}")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (m in searchable) {
                val on = m.composite in current
                FilterChip(selected = on, enabled = !op.busy, onClick = {
                    val next = if (on) current - m.composite else current + m.composite
                    scope.launch {
                        op.run("Saved.") {
                            graph.profiles.saveBackgroundModels(sub, next, searchable.map { it.composite }.toSet())
                            graph.profiles.load(sub)
                        }
                    }
                }, label = { Text(m.name.ifBlank { m.composite }) })
            }
        }
        Text("Translation", style = MaterialTheme.typography.titleSmall)
        val provider = graph.languages.translationProvider(p.data)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for ((key, label) in listOf("google" to "Google Translate", "llm" to "Gemini (honors language level)")) {
                FilterChip(selected = provider == key, enabled = !op.busy, onClick = {
                    scope.launch { op.run("Saved.") { graph.profiles.saveTranslationProvider(sub, key); graph.profiles.load(sub) } }
                }, label = { Text(label) })
            }
        }
        OpFeedback(op)
    }
}

@Composable
private fun RoleModelsSection(graph: AppGraph, p: UserProfile) {
    val scope = rememberCoroutineScope()
    val op = remember { Op() }
    val overrides = p.roleOverrides(graph.modelOverrides)
    val merged = graph.modelOverrides.merged(overrides)
    var vendor by remember { mutableStateOf(ModelVendor.entries.first()) }
    SectionCard("Models per step") {
        Row {
            VendorDropdown(vendor) { vendor = it }
        }
        val models = graph.catalogs[vendor].modelInfos()
        for ((role, label) in PHONE_ROLES) {
            val current = merged[vendor.key]?.get(role).orEmpty()
            val custom = overrides[vendor.key]?.get(role)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(label, fontWeight = FontWeight.Medium)
                    Text(current.substringAfter("/").ifBlank { "(none)" } + if (custom != null) " · custom" else "", style = MaterialTheme.typography.bodySmall)
                }
                var open by remember(vendor, role) { mutableStateOf(false) }
                TextButton(enabled = !op.busy, onClick = { open = true }) { Text("Change") }
                DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                    DropdownMenuItem(text = { Text("Default") }, onClick = {
                        open = false
                        scope.launch { op.run("Saved.") { saveOverride(graph, p, vendor.key, role, null) } }
                    })
                    for (m in models) {
                        DropdownMenuItem(text = { Text(m.name.ifBlank { m.id }) }, onClick = {
                            open = false
                            scope.launch { op.run("Saved.") { saveOverride(graph, p, vendor.key, role, m.composite) } }
                        })
                    }
                }
            }
        }
        OpFeedback(op)
    }
}

private suspend fun saveOverride(graph: AppGraph, p: UserProfile, vendor: String, role: String, composite: String?) {
    val current = p.roleOverrides(graph.modelOverrides)
    val roles = (current[vendor] ?: emptyMap()).toMutableMap()
    if (composite == null) roles.remove(role) else roles[role] = composite
    val next = current.toMutableMap()
    if (roles.isEmpty()) next.remove(vendor) else next[vendor] = roles
    val raw = JsonObject(next.mapValues { (_, r) -> JsonObject(r.mapValues { JsonPrimitive(it.value) }) })
    graph.profiles.saveRoleOverrides(p.sub, raw)
    graph.profiles.load(p.sub)
}

@Composable
private fun VendorDropdown(selected: ModelVendor, onSelect: (ModelVendor) -> Unit) {
    var open by remember { mutableStateOf(false) }
    OutlinedButton(onClick = { open = true }) { Text(selected.label) }
    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
        for (v in ModelVendor.entries) DropdownMenuItem(text = { Text(v.label) }, onClick = {
            open = false
            onSelect(v)
        })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LanguagesSection(graph: AppGraph, p: UserProfile) {
    val scope = rememberCoroutineScope()
    val op = remember { Op() }
    val saved = graph.languages.defaultLanguages(p.data)
    var entries by remember(saved) { mutableStateOf(saved) }
    SectionCard("Languages") {
        if (entries.isEmpty()) Text("No languages configured. Add them on the desktop.", style = MaterialTheme.typography.bodySmall)
        entries.forEachIndexed { idx, e ->
            fun set(n: LanguageEntry) {
                entries = entries.toMutableList().also { it[idx] = n }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(e.label.ifBlank { e.code.uppercase() }, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                Switch(checked = e.enabled, onCheckedChange = { set(e.copy(enabled = it)) })
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (lvl in graph.languages.cefrLevels) {
                    FilterChip(selected = e.level == lvl, onClick = { set(e.copy(level = lvl)) }, label = { Text(lvl) })
                }
            }
            OutlinedTextField(value = e.instructions, onValueChange = { set(e.copy(instructions = it)) }, label = { Text("Instructions for this language") }, modifier = Modifier.fillMaxWidth())
        }
        Button(enabled = !op.busy && entries != saved, onClick = {
            scope.launch { op.run("Saved.") { graph.profiles.saveLanguages(p.sub, entries); graph.profiles.load(p.sub) } }
        }) { Text("Save languages") }
        OpFeedback(op)
    }
}

@Composable
private fun DecisionModelSection(graph: AppGraph) {
    val settings by graph.deviceSettings.decisionModel.collectAsState(initial = null)
    val session by graph.flow.session.collectAsState()
    val s = settings ?: return
    val scope = rememberCoroutineScope()
    val op = remember { Op() }
    val test = remember { Op() }
    var baseUrl by remember(s) { mutableStateOf(s.baseUrl) }
    var model by remember(s) { mutableStateOf(s.model) }
    var hide by remember(s) { mutableStateOf(s.feedbackHideBelow?.toString().orEmpty()) }
    var testResult by remember { mutableStateOf<String?>(null) }

    SectionCard("Decision model") {
        Text(
            "Rescores similar letters and checks whether each feedback comment is grounded. " +
                "A comment is hidden when its grounded probability is below the hide threshold. " +
                "With no threshold, comments are scored but never hidden.",
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedTextField(value = baseUrl, onValueChange = { baseUrl = it }, label = { Text("Server URL") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = model, onValueChange = { model = it }, label = { Text("Model") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = hide, onValueChange = { hide = it }, label = { Text("Hide below (0–1, empty = never hide)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        val hideValue = hide.trim().takeIf { it.isNotEmpty() }?.toDoubleOrNull()
        val hideValid = hide.isBlank() || (hideValue != null && hideValue in 0.0..1.0)
        if (!hideValid) ErrorText("The threshold must be a number between 0 and 1.")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = hideValid && !op.busy, onClick = {
                scope.launch {
                    op.run("Saved.") {
                        graph.deviceSettings.saveDecisionModel(
                            DecisionModelSettings(
                                baseUrl = baseUrl.ifBlank { DecisionModelSettings.DEFAULT_BASE_URL },
                                model = model.ifBlank { DecisionModelSettings.DEFAULT_MODEL },
                                feedbackHideBelow = hideValue,
                            ),
                        )
                    }
                }
            }) { Text("Save") }
            OutlinedButton(enabled = !test.busy, onClick = {
                scope.launch { test.run("") { testResult = graph.flow.testDecisionModel() } }
            }) { Text("Test") }
        }
        OpFeedback(op)
        if (test.busy) BusyRow("Calling the decision model")
        testResult?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        ErrorText(test.error)

        val scored = session?.let { ws ->
            ws.vendors.flatMap { v ->
                val w = ws.vendorWork(v)
                FeedbackItems.CATEGORIES.flatMap { w.items(it) }
                    .filter { it["type"].pyStr() == FeedbackUi.PLEASE_FIX }
                    .mapNotNull { item -> item[DecisionKeys.VALID_PROBABILITY].asDoubleOrNull()?.let { Triple(v, it, item["observation"].pyStr()) } }
            }
        }.orEmpty().sortedBy { it.second }
        if (scored.isNotEmpty()) {
            Text("Scores in the letter in progress (to help pick a threshold)", style = MaterialTheme.typography.titleSmall)
            for ((v, prob, obs) in scored) {
                val hiddenNow = hideValue != null && prob < hideValue
                Text(
                    "${String.format(Locale.US, "%.2f", prob)}${if (hiddenNow) " · hidden" else ""} · ${vendorLabel(v)}: ${obs.take(140)}",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}