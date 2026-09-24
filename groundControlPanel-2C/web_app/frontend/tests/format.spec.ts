import { describe, expect, it } from 'vitest'

import { formationError, rowSeverity, storedOptionalInteger } from '../src/utils/format'

describe('telemetry display rules', () => {
  it('uses telemetry disconnection as the highest row priority', () => {
    expect(rowSeverity({ telemetry_status: 'disconnected', flight_control_status: 'dead' })).toBe('muted')
  })

  it('uses flight-controller dead before fault', () => {
    expect(rowSeverity({ telemetry_status: 'normal', flight_control_status: 'dead' })).toBe('danger')
    expect(rowSeverity({ telemetry_status: 'normal', flight_control_status: 'fault' })).toBe('warning')
  })

  it('formats two-axis and single-axis formation errors', () => {
    expect(formationError({ err_s: 3, err_d: 4 }, true)).toBe('5.0')
    expect(formationError({ err_s: -3 }, true)).toBe('3.0')
    expect(formationError({ err_s: 3, err_d: 4 }, false)).toBe('—')
  })

  it('does not turn a missing persisted selection into formation zero', () => {
    expect(storedOptionalInteger(null)).toBeNull()
    expect(storedOptionalInteger('')).toBeNull()
    expect(storedOptionalInteger('   ')).toBeNull()
    expect(storedOptionalInteger('0')).toBe(0)
    expect(storedOptionalInteger('12')).toBe(12)
    expect(storedOptionalInteger('invalid')).toBeNull()
  })
})
