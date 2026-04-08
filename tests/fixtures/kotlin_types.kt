package com.gigwell.reports.requests

import com.gigwell.reports.ExportAs

/**
 * Custom Filter Request for v0.2 MCP Server API.
 *
 * Allows submitting filter parameters directly without using a preset.
 * Supports date ranges, statuses, identities, location, and financial filters.
 */
data class CustomFilterRequest(
    var dateRange: DateRangeFilter? = null,
    var statuses: List<String>? = null,
    var identities: IdentityFilter? = null,
    var location: LocationFilter? = null,
    var financial: FinancialFilter? = null,
    var exportAs: ExportAs? = null,
    var multiValueDelimiter: String? = null
)

/**
 * Date range filter parameters.
 */
data class DateRangeFilter(
    var field: String? = null,
    var start: String? = null,
    var end: String? = null
)

/**
 * Identity filter parameters for artists, venues, buyers, and agents.
 */
data class IdentityFilter(
    var artists: List<String>? = null,
    var venues: List<String>? = null,
    var buyers: List<String>? = null,
    var agents: List<String>? = null
)

/**
 * Location filter parameters for countries, cities, and states.
 */
data class LocationFilter(
    var countries: List<String>? = null,
    var cities: List<String>? = null,
    var states: List<String>? = null
)

/**
 * Financial filter parameters for billable amounts and currency.
 */
data class FinancialFilter(
    var minBillableBase: Long? = null,
    var maxBillableBase: Long? = null,
    var currency: String? = null
)

/**
 * Export format options.
 */
enum class ExportAs {
    STREAM_JSONL,
    STREAM_CSV,
    XLSX
}
