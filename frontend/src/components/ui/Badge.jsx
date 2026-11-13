import React from 'react';

const VARIANTS = {
  default: 'bg-indigo-50 text-indigo-700 border-indigo-200/80',
  indigo: 'bg-indigo-50 text-indigo-700 border-indigo-200/80',
  emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200/80',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200/80',
  amber: 'bg-amber-50 text-amber-700 border-amber-200/80',
  warning: 'bg-amber-50 text-amber-700 border-amber-200/80',
  rose: 'bg-rose-50 text-rose-700 border-rose-200/80',
  danger: 'bg-rose-50 text-rose-700 border-rose-200/80',
  slate: 'bg-slate-100 text-slate-700 border-slate-200',
  neutral: 'bg-slate-100 text-slate-700 border-slate-200',
  purple: 'bg-purple-50 text-purple-700 border-purple-200/80',
  cyan: 'bg-cyan-50 text-cyan-700 border-cyan-200/80',
};

const SIZES = {
  sm: 'px-2 py-0.5 text-[10px] gap-1 font-medium',
  md: 'px-2.5 py-0.5 text-xs gap-1.5 font-medium',
  lg: 'px-3 py-1 text-xs gap-1.5 font-semibold',
};

export default function Badge({
  children,
  variant = 'default',
  size = 'md',
  dot = false,
  dotColor,
  icon: Icon,
  className = '',
}) {
  const variantStyles = VARIANTS[variant] || VARIANTS.default;
  const sizeStyles = SIZES[size] || SIZES.md;

  return (
    <span
      className={`inline-flex items-center rounded-full border transition-colors ${variantStyles} ${sizeStyles} ${className}`}
    >
      {dot && (
        <span
          className={`w-1.5 h-1.5 rounded-full shrink-0 ${
            dotColor || 'bg-current opacity-70'
          }`}
        />
      )}
      {Icon && <Icon className="w-3 h-3 shrink-0" />}
      <span>{children}</span>
    </span>
  );
}
