package io.github.fdondi.letterwriter.ui.write

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.PrimaryScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.pipeline.PipelineSession
import io.github.fdondi.letterwriter.pipeline.WorkSession
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.common.WarningList
import io.github.fdondi.letterwriter.ui.common.formatDollars

/** Sub-tabs of the Info page: every part of the job the letter is written for. */
private val INFO_TABS = listOf("Job offer", "Company", "Goal", "Competences", "Notes")

/**
 * Info about the job the letter is written for: the original offer, the company search, the
 * deduced goal, and the rest of the intake, each on its own sub-tab.
 */
@Composable
fun InfoPage(s: WorkSession, modifier: Modifier = Modifier) {
    var selected by rememberSaveable { mutableIntStateOf(0) }
    Column(modifier.fillMaxSize()) {
        PrimaryScrollableTabRow(selectedTabIndex = selected.coerceIn(0, INFO_TABS.size - 1), edgePadding = 8.dp) {
            INFO_TABS.forEachIndexed { idx, label ->
                Tab(selected = selected == idx, onClick = { selected = idx }, text = { Text(label) })
            }
        }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            WarningList(s.intake.warnings)
            when (selected) {
                0 -> JobOfferInfo(s)
                1 -> CompanyInfo(s)
                2 -> GoalInfo(s)
                3 -> CompetencesInfo(s)
                else -> NotesInfo(s)
            }
        }
    }
}

/** A read-only section: the text, or a line saying the part is still empty. */
@Composable
private fun InfoText(title: String, body: String, empty: String) {
    SectionCard(title) {
        Text(if (body.isNotBlank()) body else empty, style = MaterialTheme.typography.bodyMedium)
    }
}

/** The original job offer, as pasted or fetched. */
@Composable
private fun JobOfferInfo(s: WorkSession) {
    val i = s.intake
    Text(
        listOf(i.companyName, i.jobTitle).filter { it.isNotBlank() }.joinToString(" — ").ifBlank { "Untitled job" },
        style = MaterialTheme.typography.headlineSmall,
    )
    val meta = listOf(i.location, i.language, i.salary).filter { it.isNotBlank() }
    if (meta.isNotEmpty()) Text(meta.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
    if (i.sourceUrl.isNotBlank()) Text(i.sourceUrl, style = MaterialTheme.typography.bodySmall)
    InfoText("Job offer text", i.jobText, "No job offer text.")
}

/** The company search: the report every vendor wrote against, and the reports per model. */
@Composable
private fun CompanyInfo(s: WorkSession) {
    val i = s.intake
    if (i.researchSource.isNotBlank()) {
        Text(
            when (i.researchSource) {
                "cache" -> "Reused a saved report (less than 6 months old)."
                "similar" -> "Reused the saved report of a company with a similar name."
                "fixture" -> "Fixture text from the debug harness. Nothing was fetched or saved."
                PipelineSession.DESKTOP_REPORT -> "Researched by the desktop pipeline."
                else -> "New research."
            },
            style = MaterialTheme.typography.bodySmall,
        )
    }
    val cost = i.costs.values.sum()
    if (cost > 0) Text("Spent on reading and research: ${formatDollars(cost)}", style = MaterialTheme.typography.bodySmall)
    InfoText("Company report used by every vendor", i.companyReport, "No company report yet: letters are written without one.")
    if (i.companyReports.size > 1) {
        SectionCard("Reports by model") {
            for ((model, v) in i.companyReports) {
                val err = v.asObjectOrNull()?.get("error").asStringOrNull()
                Text(
                    when {
                        err != null -> "$model — failed: $err"
                        model == i.selectedReportModel -> "$model — used"
                        else -> "$model — available"
                    },
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
    if (i.pocReports.isNotEmpty()) {
        SectionCard("Point of contact reports") {
            for ((model, v) in i.pocReports) {
                val o = v.asObjectOrNull()
                Text("Point of contact ($model)", style = MaterialTheme.typography.titleSmall)
                Text(o?.get("report").asStringOrNull() ?: "Failed: ${o?.get("error").pyStr()}", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

/** The deduced goal: the problem this hire solves. The skills it needs are on the Competences tab. */
@Composable
private fun GoalInfo(s: WorkSession) {
    InfoText("What problem this hire solves", s.intake.hireProblem, "Not deduced yet — read the job offer on the Job tab.")
}

/** The key competences the offer asks for, with need and level. */
@Composable
private fun CompetencesInfo(s: WorkSession) {
    val i = s.intake
    SectionCard("Key competences") {
        if (i.competences.isEmpty()) {
            Text("No competences extracted yet.", style = MaterialTheme.typography.bodySmall)
        } else {
            for ((skill, v) in i.competences) {
                val o = v.asObjectOrNull()
                Row(Modifier.fillMaxWidth()) {
                    Text(skill, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                    Text("${o?.get("need").pyStr()} · ${o?.get("level").pyStr()}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

/** The point of contact and the notes for the model. */
@Composable
private fun NotesInfo(s: WorkSession) {
    val i = s.intake
    val poc = i.pointOfContact?.takeIf { it.isNotEmpty() }
    if (poc != null) {
        val lines = buildList {
            poc["name"].asStringOrNull()?.takeIf { it.isNotBlank() }?.let { add(it) }
            for (k in listOf("role", "contact_details", "notes")) {
                poc[k].asStringOrNull()?.takeIf { it.isNotBlank() }?.let { add("$k: $it") }
            }
        }
        InfoText("Point of contact", lines.joinToString("\n"), "No point of contact found.")
    }
    InfoText("About you, for this job", i.additionalUserInfo, "Nothing noted.")
    InfoText("About the company (used by research)", i.additionalCompanyInfo, "Nothing noted.")
}
