/**
 * Zod schemas for the application forms.
 *
 * The backend validates the same rules (and is the authority); these exist so a
 * user gets immediate, field-level feedback instead of a round trip. Keep the
 * messages user-facing and specific, and keep the two sides in step — a rule
 * that exists only here is a rule an API client can bypass.
 *
 * Every optional field stays optional here too: the platform must not demand
 * personal information to create an account.
 */

import { z } from 'zod';

import { ASSIGNABLE_ROLES, SELF_REGISTRABLE_ROLES, roleLabel } from '@/constants/roles';

const password = z
  .string({ required_error: 'Please enter a password' })
  .min(8, 'Use at least 8 characters')
  .max(72, 'Password must be 72 characters or fewer')
  .regex(/[A-Za-z]/, 'Include at least one letter')
  .regex(/[0-9]/, 'Include at least one number');

const optionalText = (max, label = 'This field') =>
  z
    .string()
    .trim()
    .max(max, `${label} must be ${max} characters or fewer`)
    .optional()
    .or(z.literal(''));

/**
 * Phone number, mirroring the API's normalisation rule exactly.
 *
 * Accepted: a 10-digit Indian mobile number (the API prefixes `+91`), or a full
 * international number in `+<country><number>` form with 8–15 digits. Spaces,
 * dashes and brackets are ignored — as they are on the server.
 *
 * Anything else (an 8-digit number, a leading zero, or a country code without
 * the `+`) is rejected *here*, on the field, instead of travelling to the API
 * and coming back as a generic "Invalid request".
 */
const phone = z
  .string()
  .trim()
  .optional()
  .or(z.literal(''))
  .refine(
    (value) => {
      if (!value) return true;
      const cleaned = value.replace(/[\s()-]/g, '');
      return /^\d{10}$/.test(cleaned) || /^\+\d{8,15}$/.test(cleaned);
    },
    {
      message:
        'Enter a 10-digit mobile number (e.g. 9876543210) or a full international number starting with +',
    },
  );

/** Indian PIN code: six digits, never starting with zero. */
const pincode = z
  .string()
  .trim()
  .optional()
  .or(z.literal(''))
  .refine((value) => !value || /^[1-9][0-9]{5}$/.test(value), {
    message: 'Enter a valid 6-digit PIN code',
  });

const yearsOfExperience = z
  .union([z.string(), z.number()])
  .optional()
  .transform((value) => (value === '' || value === undefined || value === null ? undefined : Number(value)))
  .refine((value) => value === undefined || (Number.isInteger(value) && value >= 0 && value <= 90), {
    message: 'Enter a whole number of years between 0 and 90',
  });

const hiveCount = z
  .union([z.string(), z.number()])
  .optional()
  .transform((value) => (value === '' || value === undefined || value === null ? undefined : Number(value)))
  .refine((value) => value === undefined || (Number.isInteger(value) && value >= 0 && value <= 100000), {
    message: 'Enter a whole number of hives',
  });

export const loginSchema = z.object({
  email: z
    .string({ required_error: 'Please enter your email' })
    .min(1, 'Please enter your email')
    .email('Enter a valid email address'),
  password: z.string({ required_error: 'Please enter your password' }).min(1, 'Please enter your password'),
  rememberMe: z.boolean().optional().default(false),
});

/** Apiary details — shared by the registration form and the beekeeper profile. */
export const beekeeperDetailsSchema = z.object({
  village: optionalText(120, 'Village'),
  mandal: optionalText(120, 'Mandal'),
  district: optionalText(80, 'District'),
  state: optionalText(80, 'State'),
  pincode,
  experienceYears: yearsOfExperience,
  beeSpecies: optionalText(80, 'Bee species'),
  numberOfHives: hiveCount,
});

export const registerSchema = z
  .object({
    name: z
      .string({ required_error: 'Please enter your full name' })
      .trim()
      .min(2, 'Name must be at least 2 characters')
      .max(120, 'Name must be 120 characters or fewer'),
    email: z
      .string({ required_error: 'Please enter your email' })
      .min(1, 'Please enter your email')
      .email('Enter a valid email address'),
    phone,
    role: z.enum(SELF_REGISTRABLE_ROLES, {
      errorMap: () => ({ message: 'Choose a valid role' }),
    }),
    state: optionalText(80, 'State'),
    district: optionalText(80, 'District'),
    organization: optionalText(160, 'Organisation'),
    password,
    confirmPassword: z.string({ required_error: 'Please confirm your password' }),
    acceptedTerms: z.literal(true, {
      errorMap: () => ({ message: 'Please accept the data and traceability policy to continue' }),
    }),
    // Apiary section — only meaningful for the BEEKEEPER role, and only sent then.
    beekeeper: beekeeperDetailsSchema.optional(),
  })
  .refine((values) => values.password === values.confirmPassword, {
    path: ['confirmPassword'],
    message: 'Passwords do not match',
  });

/**
 * Profile personal + location details.
 *
 * Mirrors `ProfileUpdate` on the backend. Account fields (email, role, status)
 * are intentionally absent: they are administrator-controlled, and the API
 * rejects them with 422 rather than ignoring them.
 */
export const profileDetailsSchema = z.object({
  profilePhoto: optionalText(512, 'Photo link'),
  dateOfBirth: z
    .string()
    .trim()
    .optional()
    .or(z.literal(''))
    .refine(
      (value) => {
        if (!value) return true;
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return false;
        const today = new Date();
        if (parsed > today) return false;
        const age = today.getFullYear() - parsed.getFullYear();
        return age >= 10 && age <= 120;
      },
      { message: 'Enter a valid date of birth' },
    ),
  gender: z
    .enum(['', 'male', 'female', 'other', 'prefer_not_to_say'])
    .optional()
    .transform((value) => value || undefined),
  address: optionalText(500, 'Address'),
  village: optionalText(120, 'Village'),
  mandal: optionalText(120, 'Mandal'),
  district: optionalText(80, 'District'),
  state: optionalText(80, 'State'),
  pincode,
});

/** Edit form for a beekeeper's own apiary record (self-service fields only). */
export const beekeeperProfileSchema = beekeeperDetailsSchema;

/** Cluster create/edit form. `cluster_code` is optional — the API generates one. */
export const clusterSchema = z.object({
  clusterName: z
    .string({ required_error: 'Please enter a cluster name' })
    .trim()
    .min(3, 'Cluster name must be at least 3 characters')
    .max(160, 'Cluster name must be 160 characters or fewer'),
  district: z
    .string({ required_error: 'Please enter the district' })
    .trim()
    .min(2, 'District must be at least 2 characters')
    .max(80, 'District must be 80 characters or fewer'),
  state: z
    .string({ required_error: 'Please enter the state' })
    .trim()
    .min(2, 'State must be at least 2 characters')
    .max(80, 'State must be 80 characters or fewer'),
  description: optionalText(1000, 'Description'),
  coordinatorName: optionalText(120, 'Coordinator name'),
  coordinatorPhone: phone,
});

/** Verification decision form. The API also requires remarks on rejections. */
export const verificationSchema = z
  .object({
    status: z.enum(['PENDING', 'UNDER_REVIEW', 'VERIFIED', 'REJECTED', 'SUSPENDED'], {
      errorMap: () => ({ message: 'Choose a decision' }),
    }),
    remarks: optionalText(1000, 'Remarks'),
  })
  .refine(
    (values) =>
      !['REJECTED', 'SUSPENDED'].includes(values.status) || (values.remarks || '').trim().length >= 5,
    { path: ['remarks'], message: 'Please explain this decision in at least 5 characters' },
  );

/** Roles offered on the public sign-up form, as select options. */
export const ROLE_OPTIONS = SELF_REGISTRABLE_ROLES.map((role) => ({
  value: role,
  label: roleLabel(role),
}));

/**
 * Every role an administrator may assign, as select options — the ten roles, in
 * the order the API publishes them (`GET /api/v1/roles`, which follows the
 * backend's declared administration order).
 */
export const ALL_ROLE_OPTIONS = ASSIGNABLE_ROLES.map((role) => ({
  value: role,
  label: roleLabel(role),
}));

/** Roles an administrator may filter the directory by: all of them. */
export const ROLE_FILTER_OPTIONS = ALL_ROLE_OPTIONS;

/**
 * `POST /api/v1/admin/users` — the administrator's create-user form.
 *
 * The rules mirror the API's `AdminUserCreate` exactly: the same password
 * policy as registration, the same phone normalisation, the same requirement
 * that apiary details only accompany a BEEKEEPER account. Two layers, one rule
 * — the API rejects anything this lets through.
 */
export const adminCreateUserSchema = z
  .object({
    name: z
      .string({ required_error: 'Please enter the person’s full name' })
      .trim()
      .min(2, 'Name must be at least 2 characters')
      .max(120, 'Name must be 120 characters or fewer'),
    email: z
      .string({ required_error: 'Please enter an email address' })
      .min(1, 'Please enter an email address')
      .email('Enter a valid email address'),
    phone: phone.optional().or(z.literal('')),
    role: z.enum(ASSIGNABLE_ROLES, {
      errorMap: () => ({ message: 'Choose a role for this account' }),
    }),
    status: z.enum(['active', 'inactive'], {
      errorMap: () => ({ message: 'Choose whether the account starts active' }),
    }),
    organization: optionalText(160, 'Organisation'),
    state: optionalText(80, 'State'),
    district: optionalText(80, 'District'),
    password,
    confirmPassword: z.string({ required_error: 'Please confirm the password' }),
    reason: optionalText(200, 'Reason'),
    packaging_unit_id: z.string().uuid().optional().or(z.literal('')),
  })
  .refine((values) => values.password === values.confirmPassword, {
    path: ['confirmPassword'],
    message: 'Passwords do not match',
  });

/** `PATCH /api/v1/admin/users/{id}/role`. */
export const adminRoleChangeSchema = z.object({
  role: z.enum(ASSIGNABLE_ROLES, {
    errorMap: () => ({ message: 'Choose the role this account should hold' }),
  }),
  reason: optionalText(200, 'Reason'),
});

/** Blank form state for the apiary section. */
export const EMPTY_BEEKEEPER_DETAILS = {
  village: '',
  mandal: '',
  district: '',
  state: '',
  pincode: '',
  experienceYears: '',
  beeSpecies: '',
  numberOfHives: '',
};

/** Options offered as suggestions; the API accepts any species as free text. */
export const BEE_SPECIES_OPTIONS = [
  'Apis cerana indica',
  'Apis mellifera',
  'Apis dorsata',
  'Apis florea',
  'Trigona (stingless)',
  'Mixed / multiple species',
];

export const GENDER_OPTIONS = [
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'other', label: 'Other' },
  { value: 'prefer_not_to_say', label: 'Prefer not to say' },
];

/**
 * Hive registration / edit.
 *
 * `hive_code` is deliberately absent: the backend derives it from the district
 * (`HIVE-GNT-00001`), so the form cannot offer a field the API would reject.
 * All location fields are optional — a beekeeper may register a hive before the
 * survey details are known.
 */
export const hiveSchema = z.object({
  beeSpecies: optionalText(80, 'Bee species'),
  queenStatus: z.enum(['UNKNOWN', 'PRESENT', 'REPLACED', 'MISSING'], {
    errorMap: () => ({ message: 'Choose a queen status' }),
  }),
  colonyStrength: z.enum(['UNKNOWN', 'WEAK', 'MODERATE', 'STRONG'], {
    errorMap: () => ({ message: 'Choose a colony strength' }),
  }),
  village: optionalText(120, 'Village'),
  mandal: optionalText(120, 'Mandal'),
  district: optionalText(80, 'District'),
  state: optionalText(80, 'State'),
  pincode: z
    .string()
    .trim()
    .optional()
    .or(z.literal(''))
    .refine((value) => !value || /^\d{6}$/.test(value), 'Enter a 6-digit PIN code'),
  latitude: z
    .string()
    .trim()
    .optional()
    .or(z.literal(''))
    .refine(
      (value) => !value || (Number(value) >= -90 && Number(value) <= 90),
      'Latitude must be between -90 and 90',
    ),
  longitude: z
    .string()
    .trim()
    .optional()
    .or(z.literal(''))
    .refine(
      (value) => !value || (Number(value) >= -180 && Number(value) <= 180),
      'Longitude must be between -180 and 180',
    ),
  installationDate: z.string().trim().optional().or(z.literal('')),
  notes: optionalText(2000, 'Notes'),
});

/**
 * Device registration.
 *
 * `device_id` is the hardware identifier printed on the board and is the MQTT
 * topic segment, so it is required and immutable afterwards. The MQTT topic
 * itself is derived by the backend.
 */
export const deviceSchema = z.object({
  deviceId: z
    .string()
    .trim()
    .min(4, 'Use at least 4 characters')
    .max(64, 'Use 64 characters or fewer')
    .regex(
      /^[A-Za-z0-9][A-Za-z0-9._:-]*$/,
      'Letters, digits, dot, underscore, colon and dash only',
    ),
  deviceName: optionalText(120, 'Device name'),
  hiveId: z.string().trim().min(1, 'Choose the hive this device is installed on'),
  deviceType: z.enum(['ESP32', 'ESP32_GATEWAY', 'LORA_NODE', 'OTHER'], {
    errorMap: () => ({ message: 'Choose a device type' }),
  }),
  connectionType: z.enum(['', 'WIFI', 'CELLULAR', 'LORA', 'MQTT', 'LORA_MQTT'], {
    errorMap: () => ({ message: 'Choose how the device connects' }),
  }),
  // The description is required exactly when the type is "Other" and refused
  // otherwise — the same rule the backend enforces, so a form can never submit a
  // pair the API will reject, nor pass one it should have caught.
  deviceTypeOther: z
    .string()
    .trim()
    .max(120, 'Use 120 characters or fewer')
    .optional()
    .or(z.literal('')),
  firmwareVersion: optionalText(40, 'Firmware version'),
  installedAt: z.string().trim().optional().or(z.literal('')),
}).superRefine((value, ctx) => {
  if (value.deviceType === 'OTHER' && !String(value.deviceTypeOther || '').trim()) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['deviceTypeOther'],
      message: 'Say what the hardware is: "Other" on its own records nothing.',
    });
  }
  if (value.deviceType !== 'OTHER' && String(value.deviceTypeOther || '').trim()) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['deviceTypeOther'],
      message: 'A description is only recorded when the type is Other.',
    });
  }
});

/** Sensor configuration: enabling a sensor and setting its expected cadence. */
export const sensorConfigSchema = z.object({
  enabled: z.boolean(),
  samplingInterval: z
    .string()
    .trim()
    .min(1, 'Enter the expected interval in seconds')
    .refine(
      (value) => Number.isInteger(Number(value)) && Number(value) >= 1 && Number(value) <= 86400,
      'Use a whole number of seconds between 1 and 86400',
    ),
});

/** Operator reason when a device goes into or out of maintenance. */
export const deviceStatusSchema = z.object({
  status: z.enum(['MAINTENANCE', 'ONLINE'], {
    errorMap: () => ({ message: 'Choose a status' }),
  }),
  reason: optionalText(500, 'Reason'),
});

/** Blank hive form state. */
export const EMPTY_HIVE_FORM = {
  beeSpecies: '',
  queenStatus: 'UNKNOWN',
  colonyStrength: 'UNKNOWN',
  village: '',
  mandal: '',
  district: '',
  state: '',
  pincode: '',
  latitude: '',
  longitude: '',
  installationDate: '',
  notes: '',
};

/**
 * Colony strength as *recorded by the beekeeper*.
 *
 * UNKNOWN is the honest default: the platform does not infer colony condition
 * from sensor data in this phase, so "not recorded" must stay expressible.
 */
export const COLONY_STRENGTH_OPTIONS = [
  { value: 'UNKNOWN', label: 'Not recorded' },
  { value: 'WEAK', label: 'Weak' },
  { value: 'MODERATE', label: 'Moderate' },
  { value: 'STRONG', label: 'Strong' },
];

export const QUEEN_STATUS_OPTIONS = [
  { value: 'UNKNOWN', label: 'Not recorded' },
  { value: 'PRESENT', label: 'Queen present' },
  { value: 'REPLACED', label: 'Queen replaced' },
  { value: 'MISSING', label: 'No queen seen' },
];
