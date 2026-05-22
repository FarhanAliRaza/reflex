//! Per-node bit-packed flags. Bit layout matches the plan §"NodeFlags layout":
//!
//! | bit | name                        |
//! |-----|-----------------------------|
//! | 0   | has_state_or_hooks          |
//! | 1   | has_event_triggers          |
//! | 2   | is_bare                     |
//! | 3   | is_snapshot_boundary        |
//! | 4   | propagates_hooks            |
//! | 5-6 | memoization_disposition     |
//! | 7   | is_structural_memo_child    |
//! | 8   | tag_is_none                 |
//! | 9-15| reserved                    |

/// Memoization disposition encoded in bits 5–6 of `NodeFlags`.
#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Default)]
pub enum MemoizationDisposition {
    #[default]
    Auto = 0,
    Never = 1,
    Always = 2,
}

/// Bit-packed flags carried on every `NodeSnapshot`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Default)]
pub struct NodeFlags(u16);

impl NodeFlags {
    pub const HAS_STATE_OR_HOOKS: u16 = 1 << 0;
    pub const HAS_EVENT_TRIGGERS: u16 = 1 << 1;
    pub const IS_BARE: u16 = 1 << 2;
    pub const IS_SNAPSHOT_BOUNDARY: u16 = 1 << 3;
    pub const PROPAGATES_HOOKS: u16 = 1 << 4;
    pub const IS_STRUCTURAL_MEMO_CHILD: u16 = 1 << 7;
    pub const TAG_IS_NONE: u16 = 1 << 8;

    const MEMO_DISP_SHIFT: u32 = 5;
    const MEMO_DISP_MASK: u16 = 0b11 << Self::MEMO_DISP_SHIFT;

    #[inline]
    pub const fn empty() -> Self {
        Self(0)
    }

    #[inline]
    pub const fn from_bits(bits: u16) -> Self {
        Self(bits)
    }

    #[inline]
    pub const fn bits(self) -> u16 {
        self.0
    }

    #[inline]
    pub const fn contains(self, bit: u16) -> bool {
        (self.0 & bit) == bit
    }

    #[inline]
    pub fn set(&mut self, bit: u16) {
        self.0 |= bit;
    }

    #[inline]
    pub fn clear(&mut self, bit: u16) {
        self.0 &= !bit;
    }

    #[inline]
    pub fn assign(&mut self, bit: u16, value: bool) {
        if value {
            self.set(bit);
        } else {
            self.clear(bit);
        }
    }

    #[inline]
    pub fn memoization_disposition(self) -> MemoizationDisposition {
        match (self.0 & Self::MEMO_DISP_MASK) >> Self::MEMO_DISP_SHIFT {
            1 => MemoizationDisposition::Never,
            2 => MemoizationDisposition::Always,
            _ => MemoizationDisposition::Auto,
        }
    }

    #[inline]
    pub fn set_memoization_disposition(&mut self, d: MemoizationDisposition) {
        self.0 = (self.0 & !Self::MEMO_DISP_MASK) | ((d as u16) << Self::MEMO_DISP_SHIFT);
    }
}
